"""Tests for the ProtoBuilder test helper itself."""

from google.protobuf import descriptor_pb2

from tests.proto_builder import ProtoBuilder


class TestProtoBuilderBasic:
    def test_simple_message(self) -> None:
        builder = ProtoBuilder()
        builder.message("test.Simple", {
            "name": (descriptor_pb2.FieldDescriptorProto.TYPE_STRING, 1),
            "age": (descriptor_pb2.FieldDescriptorProto.TYPE_INT32, 2),
        })
        msg = builder.build("test.Simple", name="Alice", age=30)
        assert msg.name == "Alice"
        assert msg.age == 30

    def test_nested_message(self) -> None:
        builder = ProtoBuilder()
        builder.message("test.Address", {
            "street": (descriptor_pb2.FieldDescriptorProto.TYPE_STRING, 1),
        })
        builder.message("test.Person", {
            "name": (descriptor_pb2.FieldDescriptorProto.TYPE_STRING, 1),
            "address": (descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE, 2, ".test.Address"),
        })
        addr = builder.build("test.Address", street="Main St")
        person = builder.build("test.Person", name="Alice")
        person.address.CopyFrom(addr)
        assert person.address.street == "Main St"

    def test_repeated_field(self) -> None:
        builder = ProtoBuilder()
        builder.message_with_repeated(
            "test.List",
            {"values": (descriptor_pb2.FieldDescriptorProto.TYPE_INT32, 1)},
            repeated_fields={"values"},
        )
        msg = builder.build("test.List")
        msg.values.append(1)
        msg.values.append(2)
        assert list(msg.values) == [1, 2]

    def test_map_field(self) -> None:
        builder = ProtoBuilder()
        builder.map_message(
            "test.Config",
            fields={},
            map_fields={
                "labels": (
                    descriptor_pb2.FieldDescriptorProto.TYPE_STRING,
                    descriptor_pb2.FieldDescriptorProto.TYPE_STRING,
                    1,
                ),
            },
        )
        msg = builder.build("test.Config")
        msg.labels["env"] = "prod"
        assert msg.labels["env"] == "prod"

    def test_separate_pools(self) -> None:
        """Messages from different pools are different Python types."""
        builder1 = ProtoBuilder()
        builder1.message("test.Msg", {
            "value": (descriptor_pb2.FieldDescriptorProto.TYPE_STRING, 1),
        })

        builder2 = ProtoBuilder()
        builder2.message("test.Msg", {
            "value": (descriptor_pb2.FieldDescriptorProto.TYPE_STRING, 1),
        })

        msg1 = builder1.build("test.Msg", value="hello")
        msg2 = builder2.build("test.Msg", value="hello")

        # Same logical content but different pools = different types
        assert type(msg1) is not type(msg2)
        assert msg1.value == msg2.value

    def test_enum_field(self) -> None:
        builder = ProtoBuilder()
        builder.message(
            "test.WithEnum",
            fields={
                "status": (descriptor_pb2.FieldDescriptorProto.TYPE_ENUM, 1, ".test.WithEnum.Status"),
            },
            enums={
                "Status": {"UNKNOWN": 0, "ACTIVE": 1, "INACTIVE": 2},
            },
        )
        msg = builder.build("test.WithEnum", status=1)
        assert msg.status == 1

    def test_oneof(self) -> None:
        builder = ProtoBuilder()
        builder.message(
            "test.WithOneof",
            fields={
                "str_val": (descriptor_pb2.FieldDescriptorProto.TYPE_STRING, 1),
                "int_val": (descriptor_pb2.FieldDescriptorProto.TYPE_INT32, 2),
            },
            oneofs={"value": ["str_val", "int_val"]},
        )
        msg = builder.build("test.WithOneof", str_val="hello")
        assert msg.HasField("str_val")
        assert msg.WhichOneof("value") == "str_val"
