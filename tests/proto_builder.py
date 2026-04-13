"""Shared test fixtures and ProtoBuilder helper for programmatic descriptor creation."""

from __future__ import annotations

from typing import Any

from google.protobuf import descriptor_pb2, descriptor_pool, message_factory


class ProtoBuilder:
    """Compact DSL for building protobuf descriptors programmatically.

    Reduces per-test boilerplate from ~40 lines to ~5 lines by handling
    FileDescriptorProto construction, serialization, and pool registration.

    Usage:
        builder = ProtoBuilder()
        builder.message("test.Person", {
            "name": (FieldDescriptorProto.TYPE_STRING, 1),
            "age": (FieldDescriptorProto.TYPE_INT32, 2),
        })
        PersonClass = builder.get_message_class("test.Person")
        person = PersonClass(name="Alice", age=30)
    """

    def __init__(
        self,
        pool: descriptor_pool.DescriptorPool | None = None,
        file_counter: int = 0,
    ) -> None:
        self.pool = pool or descriptor_pool.DescriptorPool()
        self._file_counter = file_counter

    def message(
        self,
        full_name: str,
        fields: dict[str, tuple[int, int] | tuple[int, int, str]],
        *,
        enums: dict[str, dict[str, int]] | None = None,
        oneofs: dict[str, list[str]] | None = None,
        repeated_fields: set[str] | None = None,
        syntax: str = "proto3",
    ) -> None:
        """Register a message type in the pool.

        Args:
            full_name: Fully qualified name (e.g., "test.Person")
            fields: Dict of field_name -> (type, number) or (type, number, type_name)
                    type is a FieldDescriptorProto.Type value
                    type_name is required for TYPE_MESSAGE and TYPE_ENUM
            enums: Optional dict of enum_name -> {value_name: number}
            oneofs: Optional dict of oneof_name -> [field_names in this oneof]
            repeated_fields: Set of field names that should be LABEL_REPEATED
            syntax: "proto2" or "proto3"
        """
        parts = full_name.rsplit(".", 1)
        package = parts[0] if len(parts) > 1 else ""
        msg_name = parts[-1]
        repeated_fields = repeated_fields or set()

        self._file_counter += 1
        file_name = f"generated_{self._file_counter}.proto"

        file_proto = descriptor_pb2.FileDescriptorProto(
            name=file_name,
            package=package,
            syntax=syntax,
        )

        msg_proto = file_proto.message_type.add()
        msg_proto.name = msg_name

        # Add enums if specified
        if enums:
            for enum_name, values in enums.items():
                enum_proto = msg_proto.enum_type.add()
                enum_proto.name = enum_name
                for val_name, val_number in values.items():
                    val_proto = enum_proto.value.add()
                    val_proto.name = val_name
                    val_proto.number = val_number

        # Build oneof name -> index mapping
        oneof_name_to_index: dict[str, int] = {}
        if oneofs:
            for oneof_name in oneofs:
                oneof_proto = msg_proto.oneof_decl.add()
                oneof_proto.name = oneof_name
                oneof_name_to_index[oneof_name] = len(msg_proto.oneof_decl) - 1

        # Build field_name -> oneof_index mapping
        field_to_oneof: dict[str, int] = {}
        if oneofs:
            for oneof_name, field_names in oneofs.items():
                for fname in field_names:
                    field_to_oneof[fname] = oneof_name_to_index[oneof_name]

        # Add fields
        for field_name, field_spec in fields.items():
            field_proto = msg_proto.field.add()
            field_proto.name = field_name
            field_proto.type = field_spec[0]
            field_proto.number = field_spec[1]

            if len(field_spec) > 2:
                field_proto.type_name = field_spec[2]  # type: ignore[index]

            if field_name in repeated_fields:
                field_proto.label = descriptor_pb2.FieldDescriptorProto.LABEL_REPEATED
            else:
                field_proto.label = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL

            # Assign to oneof if applicable
            if field_name in field_to_oneof:
                field_proto.oneof_index = field_to_oneof[field_name]

        self.pool.Add(file_proto)

    def message_with_repeated(
        self,
        full_name: str,
        fields: dict[str, tuple[int, int] | tuple[int, int, str]],
        repeated_fields: set[str] | None = None,
        *,
        syntax: str = "proto3",
    ) -> None:
        """Register a message with some repeated fields.

        Convenience alias for ``message(..., repeated_fields=...)``.
        """
        self.message(full_name, fields, repeated_fields=repeated_fields, syntax=syntax)

    def map_message(
        self,
        full_name: str,
        fields: dict[str, tuple[int, int] | tuple[int, int, str]],
        map_fields: dict[str, tuple[int, int, int]],
        *,
        syntax: str = "proto3",
    ) -> None:
        """Register a message with map fields.

        map_fields: dict of field_name -> (key_type, value_type, field_number)
        """
        parts = full_name.rsplit(".", 1)
        package = parts[0] if len(parts) > 1 else ""
        msg_name = parts[-1]

        self._file_counter += 1
        file_name = f"generated_{self._file_counter}.proto"

        file_proto = descriptor_pb2.FileDescriptorProto(
            name=file_name,
            package=package,
            syntax=syntax,
        )

        msg_proto = file_proto.message_type.add()
        msg_proto.name = msg_name

        # Regular fields
        for field_name, field_spec in fields.items():
            field_proto = msg_proto.field.add()
            field_proto.name = field_name
            field_proto.type = field_spec[0]
            field_proto.number = field_spec[1]
            field_proto.label = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL

        # Map fields (synthetic MapEntry messages)
        for map_name, (key_type, value_type, field_num) in map_fields.items():
            entry_name = f"{map_name.title().replace('_', '')}Entry"

            # Create the MapEntry message
            entry_msg = msg_proto.nested_type.add()
            entry_msg.name = entry_name
            entry_msg.options.CopyFrom(descriptor_pb2.MessageOptions(map_entry=True))

            key_field = entry_msg.field.add()
            key_field.name = "key"
            key_field.number = 1
            key_field.type = key_type
            key_field.label = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL

            value_field = entry_msg.field.add()
            value_field.name = "value"
            value_field.number = 2
            value_field.type = value_type
            value_field.label = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL

            # Add the map field to parent
            map_field = msg_proto.field.add()
            map_field.name = map_name
            map_field.number = field_num
            map_field.type = descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE
            map_field.type_name = f".{package}.{msg_name}.{entry_name}" if package else f".{msg_name}.{entry_name}"
            map_field.label = descriptor_pb2.FieldDescriptorProto.LABEL_REPEATED

        self.pool.Add(file_proto)

    def get_message_class(self, full_name: str) -> type:
        """Get the generated message class for a registered type."""
        desc = self.pool.FindMessageTypeByName(full_name)
        return message_factory.GetMessageClass(desc)

    def build(self, full_name: str, **kwargs: Any) -> Any:
        """Build a message instance with the given field values."""
        cls = self.get_message_class(full_name)
        return cls(**kwargs)
