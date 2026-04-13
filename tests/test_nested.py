"""Tests for nested message field comparison."""

from google.protobuf import descriptor_pb2

from proto_differ import ChangeType, MessageDifferencer, diff_messages
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
        Addr = b.get_message_class("test.Address")
        msg1 = b.build("test.Person", name="Alice", address=Addr(street="1st", city="NY"))
        msg2 = b.build("test.Person", name="Alice", address=Addr(street="1st", city="NY"))
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
        Addr = b.get_message_class("test.Address")
        msg1 = b.build("test.Person", name="Alice", address=Addr(street="1st", city="NY"))
        msg2 = b.build("test.Person", name="Alice", address=Addr(street="2nd", city="NY"))
        result = diff_messages(msg1, msg2)
        assert len(result) == 1
        d = result.differences[0]
        assert d.change_type == ChangeType.MODIFIED
        assert str(d.path) == "address.street"
        assert d.old_value == "1st"
        assert d.new_value == "2nd"

    def test_nested_message_added(self) -> None:
        b = _make_person_builder()
        Addr = b.get_message_class("test.Address")
        msg1 = b.build("test.Person", name="Alice")
        msg2 = b.build("test.Person", name="Alice", address=Addr(street="1st", city="NY"))
        result = diff_messages(msg1, msg2)
        assert result.has_changes()
        paths = {str(d.path) for d in result}
        assert "address.street" in paths
        assert "address.city" in paths
        assert all(d.change_type == ChangeType.ADDED for d in result)

    def test_nested_message_removed(self) -> None:
        b = _make_person_builder()
        Addr = b.get_message_class("test.Address")
        msg1 = b.build("test.Person", name="Alice", address=Addr(street="1st", city="NY"))
        msg2 = b.build("test.Person", name="Alice")
        result = diff_messages(msg1, msg2)
        assert result.has_changes()
        assert all(d.change_type == ChangeType.REMOVED for d in result)

    def test_multiple_nested_fields_changed(self) -> None:
        b = _make_person_builder()
        Addr = b.get_message_class("test.Address")
        msg1 = b.build("test.Person", name="Alice", address=Addr(street="1st", city="NY"))
        msg2 = b.build("test.Person", name="Alice", address=Addr(street="2nd", city="LA"))
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

        Coord = builder.get_message_class("test.Coord")
        Geo = builder.get_message_class("test.Geo")
        msg1 = builder.build("test.Place", name="HQ", geo=Geo(coord=Coord(lat=1.0, lng=2.0)))
        msg2 = builder.build("test.Place", name="HQ", geo=Geo(coord=Coord(lat=1.0, lng=3.0)))
        result = diff_messages(msg1, msg2)
        assert len(result) == 1
        assert str(result.differences[0].path) == "geo.coord.lng"


class TestMaxDepth:
    def test_truncates_at_max_depth(self) -> None:
        b = _make_person_builder()
        Addr = b.get_message_class("test.Address")
        msg1 = b.build("test.Person", name="Alice", address=Addr(street="1st", city="NY"))
        msg2 = b.build("test.Person", name="Alice", address=Addr(street="2nd", city="LA"))

        differ = MessageDifferencer()
        differ.max_depth = 0
        result = differ.compare(msg1, msg2)
        # At depth 0, only root fields are compared; address is a message at depth 1
        assert not result.is_complete
        assert len(result.truncated_paths) > 0

    def test_max_depth_1_compares_top_level_only(self) -> None:
        b = _make_person_builder()
        Addr = b.get_message_class("test.Address")
        msg1 = b.build("test.Person", name="X", address=Addr(street="1st", city="NY"))
        msg2 = b.build("test.Person", name="Y", address=Addr(street="2nd", city="LA"))

        differ = MessageDifferencer()
        differ.max_depth = 1
        result = differ.compare(msg1, msg2)
        # name is a scalar at depth 1, should be compared
        name_diffs = [d for d in result if str(d.path) == "name"]
        assert len(name_diffs) == 1
