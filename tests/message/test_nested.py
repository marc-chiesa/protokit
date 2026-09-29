"""Tests for nested message field comparison."""

import pytest
from google.protobuf import descriptor_pb2, descriptor_pool, message_factory

from protokit.message import ChangeType, MessageDifferencer, diff_messages
from protokit.message.comparators import FloatComparison, MessageFieldComparison
from tests.proto_builder import ProtoBuilder

T = descriptor_pb2.FieldDescriptorProto


def _make_person_builder() -> ProtoBuilder:
    """Build a schema with nested Address inside Person."""
    builder = ProtoBuilder()
    builder.message("test.Address", {
        "street": (T.TYPE_STRING, 1),
        "city": (T.TYPE_STRING, 2),
    })
    builder.message("test.Person", {
        "name": (T.TYPE_STRING, 1),
        "address": (T.TYPE_MESSAGE, 2, ".test.Address"),
    })
    return builder


class TestNestedEqual:
    def test_same_nested_values(self) -> None:
        b = _make_person_builder()
        addr_cls = b.get_message_class("test.Address")
        msg1 = b.build("test.Person", name="Alice", address=addr_cls(street="1st", city="NY"))
        msg2 = b.build("test.Person", name="Alice", address=addr_cls(street="1st", city="NY"))
        result = diff_messages(msg1, msg2)
        assert not result.has_changes()

    def test_both_nested_unset(self) -> None:
        b = _make_person_builder()
        msg1 = b.build("test.Person", name="Alice")
        msg2 = b.build("test.Person", name="Alice")
        result = diff_messages(msg1, msg2)
        assert not result.has_changes()


class TestNestedDifferences:
    def test_nested_field_changed(self) -> None:
        b = _make_person_builder()
        addr_cls = b.get_message_class("test.Address")
        msg1 = b.build("test.Person", name="Alice", address=addr_cls(street="1st", city="NY"))
        msg2 = b.build("test.Person", name="Alice", address=addr_cls(street="2nd", city="NY"))
        result = diff_messages(msg1, msg2)
        assert len(result) == 1
        d = result.differences[0]
        assert d.change_type == ChangeType.MODIFIED
        assert str(d.path) == "address.street"
        assert d.left_value == "1st"
        assert d.right_value == "2nd"

    def test_nested_message_added(self) -> None:
        b = _make_person_builder()
        addr_cls = b.get_message_class("test.Address")
        msg1 = b.build("test.Person", name="Alice")
        msg2 = b.build("test.Person", name="Alice", address=addr_cls(street="1st", city="NY"))
        result = diff_messages(msg1, msg2)
        assert result.has_changes()
        paths = {str(d.path) for d in result}
        assert "address.street" in paths
        assert "address.city" in paths
        assert all(d.change_type == ChangeType.ADDED for d in result)

    def test_nested_message_removed(self) -> None:
        b = _make_person_builder()
        addr_cls = b.get_message_class("test.Address")
        msg1 = b.build("test.Person", name="Alice", address=addr_cls(street="1st", city="NY"))
        msg2 = b.build("test.Person", name="Alice")
        result = diff_messages(msg1, msg2)
        assert result.has_changes()
        assert all(d.change_type == ChangeType.REMOVED for d in result)

    def test_multiple_nested_fields_changed(self) -> None:
        b = _make_person_builder()
        addr_cls = b.get_message_class("test.Address")
        msg1 = b.build("test.Person", name="Alice", address=addr_cls(street="1st", city="NY"))
        msg2 = b.build("test.Person", name="Alice", address=addr_cls(street="2nd", city="LA"))
        result = diff_messages(msg1, msg2)
        assert len(result) == 2
        paths = {str(d.path) for d in result}
        assert paths == {"address.street", "address.city"}


class TestDeeplyNested:
    def test_three_levels_deep(self) -> None:
        """A -> B -> C, change at leaf level."""
        builder = ProtoBuilder()
        builder.message("test.Coord", {
            "lat": (T.TYPE_DOUBLE, 1),
            "lng": (T.TYPE_DOUBLE, 2),
        })
        builder.message("test.Geo", {
            "coord": (T.TYPE_MESSAGE, 1, ".test.Coord"),
        })
        builder.message("test.Place", {
            "name": (T.TYPE_STRING, 1),
            "geo": (T.TYPE_MESSAGE, 2, ".test.Geo"),
        })

        coord_cls = builder.get_message_class("test.Coord")
        geo_cls = builder.get_message_class("test.Geo")
        msg1 = builder.build(
            "test.Place", name="HQ", geo=geo_cls(coord=coord_cls(lat=1.0, lng=2.0)),
        )
        msg2 = builder.build(
            "test.Place", name="HQ", geo=geo_cls(coord=coord_cls(lat=1.0, lng=3.0)),
        )
        result = diff_messages(msg1, msg2)
        assert len(result) == 1
        assert str(result.differences[0].path) == "geo.coord.lng"


class TestMaxDepth:
    def test_truncates_at_max_depth(self) -> None:
        b = _make_person_builder()
        addr_cls = b.get_message_class("test.Address")
        msg1 = b.build("test.Person", name="Alice", address=addr_cls(street="1st", city="NY"))
        msg2 = b.build("test.Person", name="Alice", address=addr_cls(street="2nd", city="LA"))

        differ = MessageDifferencer()
        differ.max_depth = 0
        result = differ.compare(msg1, msg2)
        # At depth 0, only root fields are compared; address is a message at depth 1
        assert not result.is_complete
        assert len(result.truncated_paths) > 0

    def test_max_depth_1_compares_top_level_only(self) -> None:
        b = _make_person_builder()
        addr_cls = b.get_message_class("test.Address")
        msg1 = b.build("test.Person", name="X", address=addr_cls(street="1st", city="NY"))
        msg2 = b.build("test.Person", name="Y", address=addr_cls(street="2nd", city="LA"))

        differ = MessageDifferencer()
        differ.max_depth = 1
        result = differ.compare(msg1, msg2)
        # name is a scalar at depth 1, should be compared
        name_diffs = [d for d in result if str(d.path) == "name"]
        assert len(name_diffs) == 1


# ---------------------------------------------------------------------------
# Groups compared by content
#
# A proto2 group and an editions DELIMITED field are both TYPE_GROUP. The
# differ dispatched only TYPE_MESSAGE into field-by-field comparison, so a
# group was compared as one opaque value: ignore_fields, float tolerance and
# presence mode never reached inside it, a change was reported at the group
# rather than the inner field, and identical groups from two pools compared
# unequal.
# ---------------------------------------------------------------------------


_F = descriptor_pb2.FieldDescriptorProto
_OPT, _REP = _F.LABEL_OPTIONAL, _F.LABEL_REPEATED


def _group_schema(
    kind: str, *, g_target: str = "G", omit: tuple[str, ...] = (),
) -> descriptor_pb2.FileDescriptorProto:
    """``t.M`` holding groups ``g``, ``item`` (repeated) and ``outer.inner``.

    ``proto2`` declares real groups; ``editions`` declares message fields in a
    file whose features make every message field DELIMITED (TYPE_GROUP too).
    """
    if kind == "editions":
        fdp = descriptor_pb2.FileDescriptorProto(
            name="g.proto", package="t", syntax="editions", edition=descriptor_pb2.EDITION_2023,
        )
        fdp.options.features.message_encoding = descriptor_pb2.FeatureSet.DELIMITED
        group_type = _F.TYPE_MESSAGE
    else:
        fdp = descriptor_pb2.FileDescriptorProto(name="g.proto", package="t", syntax="proto2")
        group_type = _F.TYPE_MESSAGE if kind == "message" else _F.TYPE_GROUP
    m = fdp.message_type.add(name="M")
    for name in ("G", "H"):
        g = m.nested_type.add(name=name)
        g.field.add(name="x", number=1, type=_F.TYPE_INT32, label=_OPT)
        g.field.add(name="f", number=2, type=_F.TYPE_FLOAT, label=_OPT)
    if "g" not in omit:
        m.field.add(
            name="g", number=1, type=group_type, label=_OPT, type_name=f".t.M.{g_target}",
        )
    item = m.nested_type.add(name="Item")
    item.field.add(name="id", number=1, type=_F.TYPE_STRING, label=_OPT)
    item.field.add(name="v", number=2, type=_F.TYPE_INT32, label=_OPT)
    if "item" not in omit:
        m.field.add(name="item", number=2, type=group_type, label=_REP, type_name=".t.M.Item")
    outer = m.nested_type.add(name="Outer")
    inner = outer.nested_type.add(name="Inner")
    inner.field.add(name="deep", number=1, type=_F.TYPE_INT32, label=_OPT)
    outer.field.add(
        name="inner", number=1, type=group_type, label=_OPT, type_name=".t.M.Outer.Inner",
    )
    outer.field.add(name="parts", number=2, type=group_type, label=_REP, type_name=".t.M.Item")
    m.field.add(name="outer", number=3, type=group_type, label=_OPT, type_name=".t.M.Outer")
    return fdp


def _group_class(kind: str, **schema):
    pool = descriptor_pool.DescriptorPool()
    pool.Add(_group_schema(kind, **schema))
    desc = pool.FindMessageTypeByName("t.M")
    expected = _F.TYPE_MESSAGE if kind == "message" else _F.TYPE_GROUP
    assert desc.fields_by_name["outer"].type == expected
    return message_factory.GetMessageClass(desc)


_KINDS = pytest.mark.parametrize("kind", ["proto2", "editions"])


def _paths(result) -> set[tuple[str, ChangeType]]:
    return {(str(d.path), d.change_type) for d in result.differences}


@_KINDS
class TestGroupsComparedByContent:
    def test_an_inner_change_is_reported_at_the_inner_field(self, kind: str) -> None:
        cls = _group_class(kind)
        left, right = cls(), cls()
        left.g.x, right.g.x = 1, 2
        assert _paths(MessageDifferencer().compare(left, right)) == {("g.x", ChangeType.MODIFIED)}

    def test_identical_groups_from_two_pools_are_equal(self, kind: str) -> None:
        left, right = _group_class(kind)(), _group_class(kind)()
        left.g.x = right.g.x = 7
        left.item.add(id="a", v=1)
        right.item.add(id="a", v=1)
        assert MessageDifferencer().compare(left, right).differences == ()

    def test_an_inner_change_across_two_pools_is_reported_at_the_inner_field(
        self, kind: str,
    ) -> None:
        left, right = _group_class(kind)(), _group_class(kind)()
        left.g.x, right.g.x = 1, 2
        assert _paths(MessageDifferencer().compare(left, right)) == {("g.x", ChangeType.MODIFIED)}

    @pytest.mark.parametrize("selector", ["g.x", "x"])
    def test_ignore_fields_reaches_inside_a_group(self, kind: str, selector: str) -> None:
        cls = _group_class(kind)
        left, right = cls(), cls()
        left.g.x, right.g.x = 1, 2
        differ = MessageDifferencer()
        differ.ignore_fields(selector)
        assert differ.compare(left, right).differences == ()

    def test_float_tolerance_applies_inside_a_group(self, kind: str) -> None:
        cls = _group_class(kind)
        left, right = cls(), cls()
        left.g.f, right.g.f = 1.0, 1.0001
        differ = MessageDifferencer()
        differ.set_float_comparison(FloatComparison.APPROXIMATE, fraction=1e-3)
        assert differ.compare(left, right).differences == ()

    def test_equivalent_presence_applies_inside_a_group(self, kind: str) -> None:
        cls = _group_class(kind)
        left, right = cls(), cls()
        left.g.x = 0  # set to its default on one side only
        right.g.SetInParent()
        assert MessageDifferencer().compare(left, right).differences == ()
        strict = MessageDifferencer()
        strict.set_message_field_comparison(MessageFieldComparison.EQUAL)
        assert _paths(strict.compare(left, right)) == {("g.x", ChangeType.REMOVED)}

    def test_treat_as_map_pairs_repeated_groups_by_key(self, kind: str) -> None:
        cls = _group_class(kind)
        left, right = cls(), cls()
        left.item.add(id="a", v=1)
        left.item.add(id="b", v=2)
        right.item.add(id="b", v=2)
        right.item.add(id="a", v=9)
        differ = MessageDifferencer()
        differ.treat_as_map("item", key="id")
        assert _paths(differ.compare(left, right)) == {('item[id="a"].v', ChangeType.MODIFIED)}

    def test_treat_as_set_matches_repeated_groups_regardless_of_order(self, kind: str) -> None:
        cls = _group_class(kind)
        left, right = cls(), cls()
        left.item.add(id="a", v=1)
        left.item.add(id="b", v=2)
        right.item.add(id="b", v=2)
        right.item.add(id="a", v=1)
        differ = MessageDifferencer()
        differ.treat_as_set("item")
        assert differ.compare(left, right).differences == ()

    def test_treat_as_set_reports_unmatched_groups_like_unmatched_messages(
        self, kind: str,
    ) -> None:
        def paths(schema_kind: str):
            cls = _group_class(schema_kind)
            left, right = cls(), cls()
            left.item.add(id="a", v=1)
            left.item.add(id="b", v=2)
            right.item.add(id="c", v=3)
            right.item.add(id="a", v=1)
            differ = MessageDifferencer()
            differ.treat_as_set("item")
            return _paths(differ.compare(left, right))

        # b is left only (REMOVED at its left index), c right only (ADDED at its right index).
        assert paths(kind) == paths("message") == {
            ("item[1].id", ChangeType.REMOVED),
            ("item[1].v", ChangeType.REMOVED),
            ("item[0].id", ChangeType.ADDED),
            ("item[0].v", ChangeType.ADDED),
        }

    def test_max_depth_truncates_inside_nested_groups(self, kind: str) -> None:
        cls = _group_class(kind)
        left, right = cls(), cls()
        left.outer.inner.deep, right.outer.inner.deep = 1, 2
        differ = MessageDifferencer()
        differ.max_depth = 1
        result = differ.compare(left, right)
        assert result.differences == ()
        assert [str(p) for p in result.truncated_paths] == ["outer.inner"]
        assert not result.is_complete


def _only_left_group(msg) -> None:
    msg.g.x = 1


def _only_left_items(msg) -> None:
    msg.item.add(id="a", v=1)
    msg.item.add(id="b", v=2)


def _only_left_nested(msg) -> None:
    msg.outer.inner.deep = 3


def _only_left_nested_items(msg) -> None:
    msg.outer.parts.add(id="a", v=1)


@_KINDS
@pytest.mark.parametrize(
    "populate", [_only_left_group, _only_left_items, _only_left_nested, _only_left_nested_items],
)
@pytest.mark.parametrize("left_side", [True, False])
def test_a_group_on_one_side_is_reported_like_a_message_on_one_side(
    kind: str, populate, left_side: bool,
) -> None:
    """One-sided groups are walked into, exactly as a message field is."""
    def paths(schema_kind: str):
        cls = _group_class(schema_kind)
        filled, empty = cls(), cls()
        populate(filled)
        left, right = (filled, empty) if left_side else (empty, filled)
        return _paths(MessageDifferencer().compare(left, right))

    twin = paths("message")
    assert twin and all(p != "g" and "." in p for p, _ in twin)
    assert paths(kind) == twin


@_KINDS
@pytest.mark.parametrize(
    ("field", "populate"), [("g", _only_left_group), ("item", _only_left_items)],
)
@pytest.mark.parametrize("left_side", [True, False])
def test_a_group_declared_in_only_one_schema_is_reported_like_a_message(
    kind: str, field: str, populate, left_side: bool,
) -> None:
    """A group the other schema does not declare is walked into, like a message field."""
    def paths(schema_kind: str):
        filled = _group_class(schema_kind)()
        empty = _group_class(schema_kind, omit=(field,))()
        populate(filled)
        left, right = (filled, empty) if left_side else (empty, filled)
        return _paths(MessageDifferencer().compare(left, right))

    twin = paths("message")
    assert twin and all("." in p for p, _ in twin)
    assert paths(kind) == twin


@_KINDS
def test_strict_schema_reports_a_retargeted_group_like_a_retargeted_message(kind: str) -> None:
    def warnings(schema_kind: str):
        left, right = _group_class(schema_kind)(), _group_class(schema_kind, g_target="H")()
        differ = MessageDifferencer()
        differ.strict_schema = True
        return [w.message for w in differ.compare(left, right).warnings]

    twin = warnings("message")
    assert any("t.M.G" in w and "t.M.H" in w for w in twin)
    assert warnings(kind) == twin


@_KINDS
@pytest.mark.parametrize("group_on_left", [True, False])
def test_a_group_switched_to_a_message_is_a_type_change_not_walked(
    kind: str, group_on_left: bool,
) -> None:
    """Group and message framing differ on the wire, so the switch is not descended."""
    group, message = _group_class(kind)(), _group_class("message")()
    for msg in (group, message):
        msg.g.x = 1
        msg.item.add(id="a", v=1)
        msg.outer.inner.deep = 2
    left, right = (group, message) if group_on_left else (message, group)
    assert _paths(MessageDifferencer().compare(left, right)) == {
        ("g", ChangeType.TYPE_CHANGED),
        ("item", ChangeType.TYPE_CHANGED),
        ("outer", ChangeType.TYPE_CHANGED),
    }
