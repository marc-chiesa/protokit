"""Shared test fixtures and ProtoBuilder helper for programmatic descriptor creation."""

from __future__ import annotations

from typing import Any

from google.protobuf import descriptor_pb2, descriptor_pool, message_factory


def _declared_type_names(file_proto: descriptor_pb2.FileDescriptorProto) -> set[str]:
    """Fully-qualified names of every message and enum ``file_proto`` declares."""
    package = file_proto.package
    names: set[str] = set()

    def _walk(msg: descriptor_pb2.DescriptorProto, prefix: str) -> None:
        full = f"{prefix}.{msg.name}" if prefix else msg.name
        names.add(full)
        for enum in msg.enum_type:
            names.add(f"{full}.{enum.name}")
        for nested in msg.nested_type:
            _walk(nested, full)

    for msg in file_proto.message_type:
        _walk(msg, package)
    for enum in file_proto.enum_type:
        names.add(f"{package}.{enum.name}" if package else enum.name)
    return names


def _referenced_type_names(file_proto: descriptor_pb2.FileDescriptorProto) -> list[str]:
    """Every ``type_name`` a field in ``file_proto`` references, in source order."""
    refs: list[str] = []

    def _walk(msg: descriptor_pb2.DescriptorProto) -> None:
        for field in msg.field:
            if field.type_name:
                refs.append(field.type_name)
        for nested in msg.nested_type:
            _walk(nested)

    for msg in file_proto.message_type:
        _walk(msg)
    for ext in file_proto.extension:
        if ext.type_name:
            refs.append(ext.type_name)
    return refs


def wire_dependencies(
    file_proto: descriptor_pb2.FileDescriptorProto,
    pool: descriptor_pool.DescriptorPool,
) -> None:
    """Record the file of every cross-file referent in ``file_proto.dependency``.

    Test builders emit one ``FileDescriptorProto`` per message and reference
    earlier types by ``type_name`` alone. The upb backend resolves such a
    reference from the whole pool, so the missing ``dependency`` entry was
    invisible for the suite's entire life; the pure-Python backend resolves
    ``type_name`` only through the file's declared dependencies and raises
    ``KeyError`` at the first lookup (KTD11). Call this immediately before
    ``pool.Add(file_proto)``.

    Resolution goes through ``pool`` — never a builder-local file list —
    because several call sites pre-populate a shared pool by hand. A referent
    that is not in the pool (a same-file or forward reference) is a miss, not
    an error; the same-file case is additionally excluded by name so a shared
    pool that already holds an identically named type from another file does
    not acquire a spurious edge. Each dependency is recorded once, in
    first-reference order.
    """
    declared = _declared_type_names(file_proto)
    package = file_proto.package
    for type_name in _referenced_type_names(file_proto):
        candidates = [type_name.lstrip(".")]
        if package and not candidates[0].startswith(f"{package}."):
            candidates.append(f"{package}.{candidates[0]}")
        if any(c in declared for c in candidates):
            continue
        referent = None
        for candidate in candidates:
            for finder in (pool.FindMessageTypeByName, pool.FindEnumTypeByName):
                try:
                    referent = finder(candidate)
                except KeyError:
                    continue
                break
            if referent is not None:
                break
        if referent is None:
            continue
        dep_name = referent.file.name
        if dep_name != file_proto.name and dep_name not in file_proto.dependency:
            file_proto.dependency.append(dep_name)


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
        optional_fields: set[str] | None = None,
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
            optional_fields: Set of field names that should be proto3 ``optional``
                (explicit presence). Each named field gets ``proto3_optional=True``
                AND a compiler-synthesized ``_<field>`` oneof wrapping it, exactly
                as ``protoc`` emits — so ``HasField`` works and ``has_presence``
                is True. Only meaningful for singular scalar/enum fields under
                ``syntax="proto3"``; a field cannot be both proto3-optional and
                repeated or a member of a user-declared oneof.
            syntax: "proto2" or "proto3"
        """
        parts = full_name.rsplit(".", 1)
        package = parts[0] if len(parts) > 1 else ""
        msg_name = parts[-1]
        repeated_fields = repeated_fields or set()
        optional_fields = optional_fields or set()

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
            elif field_name in optional_fields:
                # proto3 ``optional``: protoc marks the field proto3_optional and
                # wraps it in a compiler-synthesized ``_<field>`` oneof appended
                # AFTER any user-declared oneofs. This gives the field explicit
                # presence (HasField / has_presence) without it behaving as a
                # user oneof member. The leading underscore is the synthetic-oneof
                # discriminator presence logic must skip (KTD-7).
                synthetic = msg_proto.oneof_decl.add()
                synthetic.name = f"_{field_name}"
                field_proto.proto3_optional = True
                field_proto.oneof_index = len(msg_proto.oneof_decl) - 1

        wire_dependencies(file_proto, self.pool)
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
            map_field.type_name = (
                f".{package}.{msg_name}.{entry_name}" if package else f".{msg_name}.{entry_name}"
            )
            map_field.label = descriptor_pb2.FieldDescriptorProto.LABEL_REPEATED

        wire_dependencies(file_proto, self.pool)
        self.pool.Add(file_proto)

    def get_message_class(self, full_name: str) -> type:
        """Get the generated message class for a registered type."""
        desc = self.pool.FindMessageTypeByName(full_name)
        return message_factory.GetMessageClass(desc)

    def build(self, full_name: str, **kwargs: Any) -> Any:
        """Build a message instance with the given field values."""
        cls = self.get_message_class(full_name)
        return cls(**kwargs)
