"""Core protobuf message comparison engine.

Uses an iterative explicit stack (no recursion) with name-based field matching
for cross-descriptor-pool comparison and schema evolution detection.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from google.protobuf import descriptor as proto_descriptor
from google.protobuf.message import Message

from protokit._descriptors import (
    format_key,
    get_field_map,
    has_presence,
    is_map_field,
    type_name,
)
from protokit.message.comparators import (
    FloatComparison,
    FloatConfig,
    compare_enum_cross_pool,
    compare_enum_same_pool,
    compare_float,
    compare_scalar,
    to_enum_value,
)
from protokit.message.model import (
    ChangeType,
    Difference,
    DiffResult,
    DuplicateKeyError,
    FieldPath,
    MissingKeyError,
    PathSegment,
    Warning,
)

# Protobuf field type constants
FD = proto_descriptor.FieldDescriptor
TYPE_MESSAGE = FD.TYPE_MESSAGE
TYPE_ENUM = FD.TYPE_ENUM
TYPE_FLOAT = FD.TYPE_FLOAT
TYPE_DOUBLE = FD.TYPE_DOUBLE
TYPE_BYTES = FD.TYPE_BYTES
TYPE_BOOL = FD.TYPE_BOOL
TYPE_STRING = FD.TYPE_STRING
LABEL_REPEATED = FD.LABEL_REPEATED

def _replace_bracket(path: FieldPath, bracket: str) -> FieldPath:
    """Return a new FieldPath with the last segment's bracket replaced.

    Args:
        path: The original field path.
        bracket: New bracket content for the last segment.

    Returns:
        A new FieldPath identical to ``path`` except the last segment
        carries the given bracket.
    """
    last = path.segments[-1]
    new_seg = PathSegment(name=last.name, bracket=bracket)
    return FieldPath(segments=path.segments[:-1] + (new_seg,))


# Type compatibility groups
_INTEGER_TYPES = frozenset({
    FD.TYPE_INT32, FD.TYPE_INT64, FD.TYPE_UINT32, FD.TYPE_UINT64,
    FD.TYPE_SINT32, FD.TYPE_SINT64, FD.TYPE_FIXED32, FD.TYPE_FIXED64,
    FD.TYPE_SFIXED32, FD.TYPE_SFIXED64,
})
_FLOAT_TYPES = frozenset({FD.TYPE_FLOAT, FD.TYPE_DOUBLE})

def _types_compatible(left_type: int, right_type: int) -> bool:
    """Check if two protobuf field types are compatible for value comparison.

    Args:
        left_type: Field type constant from the left descriptor.
        right_type: Field type constant from the right descriptor.

    Returns:
        True if the types are the same or belong to the same
        compatibility group (integer types, float types, or message types).
    """
    if left_type == right_type:
        return True
    if left_type in _INTEGER_TYPES and right_type in _INTEGER_TYPES:
        return True
    if left_type in _FLOAT_TYPES and right_type in _FLOAT_TYPES:
        return True
    return False


def _same_pool(left_msg: Message, right_msg: Message) -> bool:
    """Check if two messages are from the same descriptor pool.

    Args:
        left_msg: The left protobuf Message.
        right_msg: The right protobuf Message.

    Returns:
        True if both message descriptors reference the same pool object.
    """
    return left_msg.DESCRIPTOR.file.pool is right_msg.DESCRIPTOR.file.pool


# ---------------------------------------------------------------------------
# Work item for the iterative stack
# ---------------------------------------------------------------------------

@dataclass
class _WorkItem:
    """A unit of comparison work for the stack-based engine."""

    left_msg: Message | None
    right_msg: Message | None
    path: FieldPath
    depth: int


# ---------------------------------------------------------------------------
# MessageDifferencer
# ---------------------------------------------------------------------------


class MessageDifferencer:
    """Configurable protobuf message comparator.

    Uses an iterative explicit stack for unbounded depth support.
    Name-based field matching enables cross-descriptor-pool
    comparison and schema-evolution detection.

    Configure behavior by calling the instance methods
    (:meth:`ignore_fields`, :meth:`treat_as_map`,
    :meth:`set_float_comparison`) or by assigning to the public
    attributes below before calling :meth:`compare`.

    Attributes:
        max_depth: Maximum recursion depth (``None`` for unlimited,
            the default). Subtrees below the limit are not compared
            and their paths appear in ``DiffResult.truncated_paths``.
        strict_schema: When True (default False), emit a ``Warning``
            if two compared messages have different fully-qualified
            type names, even if their field shapes align.
    """

    def __init__(self) -> None:
        """Construct a differencer with default configuration.

        All configuration starts empty — no ignored fields, no
        ``treat_as_map`` entries, exact float comparison, unlimited
        depth, lenient schema mode. Use the instance methods below
        to customize.
        """
        self._ignore_names: set[str] = set()  # bare names (global match)
        self._ignore_paths: list[FieldPath] = []  # parsed dotted paths
        self._ignore_fields_raw: list[str] = []  # raw selectors for conflict validation
        self._treat_as_map: dict[str, str] = {}  # field_name_or_path -> key_field_name
        self._treat_as_map_paths: list[tuple[FieldPath, str]] = []  # (parsed_path, key_name)
        self._float_config = FloatConfig()
        self.max_depth: int | None = None
        self.strict_schema: bool = False

    def ignore_fields(self, *selectors: str) -> None:
        """Add field name selectors to the ignore list.

        Bare names apply globally. Dotted paths match specific locations.

        Args:
            *selectors: One or more field selectors. A bare name (e.g.
                ``"timestamp"``) ignores that field everywhere. A dotted
                path (e.g. ``"header.timestamp"``) ignores only that
                specific location.

        Raises:
            ValueError: If a selector conflicts with a ``treat_as_map``
                configuration (e.g. ignoring a map key field).
        """
        # Validate all selectors before mutating state
        for sel in selectors:
            if "[" in sel:
                raise ValueError(
                    f"Bracket syntax is not supported in ignore selectors: '{sel}'. "
                    "Use bare field names or dotted paths (e.g. 'field' or 'parent.field')."
                )
            if sel in self._treat_as_map:
                raise ValueError(
                    f"Cannot ignore field '{sel}' that is configured as treat_as_map"
                )

        # Check for conflicts with treat_as_map key fields
        for map_sel, key_name in self._treat_as_map.items():
            for ign in selectors:
                # Bare name that matches the key
                if "." not in ign and ign == key_name:
                    raise ValueError(
                        f"Cannot ignore '{ign}' globally because it's the key field "
                        f"for treat_as_map('{map_sel}', key='{key_name}')"
                    )
                # Path-scoped that targets the key inside the map field
                if "." in ign and ign == f"{map_sel}.{key_name}":
                    raise ValueError(
                        f"Cannot ignore '{ign}' because it's the key field "
                        f"for treat_as_map('{map_sel}', key='{key_name}')"
                    )

        # All validation passed — safe to mutate
        self._ignore_fields_raw.extend(selectors)
        for sel in selectors:
            if "." in sel:
                self._ignore_paths.append(FieldPath.parse(sel))
            else:
                self._ignore_names.add(sel)

    def treat_as_map(self, field_selector: str, *, key: str) -> None:
        """Configure a repeated message field for key-based matching.

        Instead of pairing repeated-field elements by index, the
        engine will match elements by the value of the given key
        sub-field. Paths for matched elements use the
        ``items[key="abc"].field`` form. Elements with duplicate or
        missing keys raise ``DuplicateKeyError`` / ``MissingKeyError``.

        Args:
            field_selector: Bare field name (``"items"``) for a
                global match or dotted path (``"parent.items"``) for
                a scoped match. The field must be a repeated message
                field on both sides.
            key: Name of the scalar sub-field to use as the map key.
                Must be a scalar type (string, int, bool, enum).

        Raises:
            ValueError: If ``field_selector`` or ``key`` conflicts
                with an existing ignore configuration, or if the
                same field is already configured with a different
                key.
        """
        # Check for conflicts with already-configured ignore fields
        for ign in self._ignore_fields_raw:
            # The field itself is ignored
            if ign == field_selector:
                raise ValueError(
                    f"Cannot treat_as_map field '{field_selector}' that is "
                    f"already ignored"
                )
            # Bare name that matches the key
            if "." not in ign and ign == key:
                raise ValueError(
                    f"Cannot use key '{key}' for treat_as_map('{field_selector}') "
                    f"because '{ign}' is globally ignored"
                )
            # Path-scoped that targets the key inside the map field
            if "." in ign and ign == f"{field_selector}.{key}":
                raise ValueError(
                    f"Cannot use key '{key}' for treat_as_map('{field_selector}') "
                    f"because '{ign}' is ignored"
                )

        self._treat_as_map[field_selector] = key
        if "." in field_selector:
            self._treat_as_map_paths.append((FieldPath.parse(field_selector), key))

    def set_float_comparison(
        self,
        mode: FloatComparison,
        fraction: float = 1e-6,
        margin: float = 1e-9,
    ) -> None:
        """Configure how float (and double) fields are compared.

        Default is exact IEEE 754 comparison.

        Args:
            mode: ``FloatComparison.EXACT`` for bit-identical
                comparison (NaN != NaN, ±0 distinguished) or
                ``FloatComparison.APPROXIMATE`` for tolerance-based
                comparison using ``fraction`` and ``margin``.
            fraction: Relative tolerance for approximate mode:
                values are equal if ``|a - b| <= fraction * max(|a|, |b|)``.
                Defaults to ``1e-6``. Ignored in EXACT mode.
            margin: Absolute tolerance for approximate mode: values
                are equal if ``|a - b| <= margin``. Combined with
                ``fraction`` as a logical OR. Defaults to ``1e-9``.
                Ignored in EXACT mode.
        """
        self._float_config = FloatConfig(mode=mode, fraction=fraction, margin=margin)

    def compare(self, left: Message, right: Message) -> DiffResult:
        """Compare two protobuf messages and return a structured diff.

        The traversal uses an explicit stack, so recursion depth is
        bounded by ``max_depth`` (unlimited by default), not by the
        Python call stack. Name-based field matching lets ``left``
        and ``right`` come from different descriptor pools.

        Args:
            left: The left-side protobuf ``Message``. Treated as the
                "old" or "expected" side for directional semantics
                like ``ChangeType.REMOVED``.
            right: The right-side protobuf ``Message``. Treated as
                the "new" or "actual" side.

        Returns:
            A ``DiffResult`` with every detected ``Difference``,
            any ``Warning`` diagnostics (schema drift, cardinality
            change, ``treat_as_map`` fallbacks), and the set of
            paths where ``max_depth`` cut off traversal. Differences
            are sorted by path for deterministic output.

        Raises:
            DuplicateKeyError: A ``treat_as_map``-configured field
                had duplicate keys in one side's elements.
            MissingKeyError: A ``treat_as_map``-configured field had
                an element with the key sub-field unset.
        """
        differences: list[Difference] = []
        warnings: list[Warning] = []
        truncated_paths: list[FieldPath] = []
        same_pool = _same_pool(left, right)

        stack: list[_WorkItem] = [_WorkItem(left, right, FieldPath(segments=()), 0)]

        while stack:
            item = stack.pop()

            # Max depth check
            if self.max_depth is not None and item.depth > self.max_depth:
                truncated_paths.append(item.path)
                warnings.append(Warning(
                    path=str(item.path) if item.path else None,
                    message=f"comparison truncated at depth {self.max_depth}; "
                            "differences below this path are not reported",
                ))
                continue

            if item.left_msg is None and item.right_msg is None:
                continue

            # Unset -> set (or vice versa) for message fields
            if item.left_msg is None and item.right_msg is not None:
                self._emit_all_fields(item.right_msg, item.path, ChangeType.ADDED,
                                      differences, is_new=True, depth=item.depth,
                                      warnings=warnings, truncated_paths=truncated_paths)
                continue
            if item.left_msg is not None and item.right_msg is None:
                self._emit_all_fields(item.left_msg, item.path, ChangeType.REMOVED,
                                      differences, is_new=False, depth=item.depth,
                                      warnings=warnings, truncated_paths=truncated_paths)
                continue

            assert item.left_msg is not None and item.right_msg is not None

            left_fields = get_field_map(item.left_msg.DESCRIPTOR)
            right_fields = get_field_map(item.right_msg.DESCRIPTOR)

            all_names = left_fields.keys() | right_fields.keys()

            # Sort by left-side field number for deterministic ordering
            def _sort_key(name: str) -> tuple[int, int, str]:
                if name in left_fields:
                    return (0, left_fields[name].number, name)
                return (1, right_fields[name].number, name)

            # Process in reverse order since we're using a stack (LIFO)
            sorted_names = sorted(all_names, key=_sort_key, reverse=True)

            for field_name in sorted_names:
                # Fast path: check bare-name ignore before allocating FieldPath
                if field_name in self._ignore_names:
                    continue
                field_path = item.path.child(field_name)

                # Check path-scoped ignores
                if self._ignore_paths and self._is_ignored(field_name, field_path):
                    continue

                left_fd = left_fields.get(field_name)
                right_fd = right_fields.get(field_name)

                # Field only on one side
                if left_fd is None and right_fd is not None:
                    self._emit_one_sided(
                        item.right_msg, right_fd, field_path,
                        differences, stack, item.depth, is_new=True,
                    )
                    continue
                if left_fd is not None and right_fd is None:
                    self._emit_one_sided(
                        item.left_msg, left_fd, field_path,
                        differences, stack, item.depth, is_new=False,
                    )
                    continue

                assert left_fd is not None and right_fd is not None

                # Schema evolution checks
                self._check_schema_evolution(
                    left_fd, right_fd, field_path, differences, warnings
                )

                # Cardinality change -> no value comparison
                if left_fd.is_repeated != right_fd.is_repeated:
                    continue
                left_is_map = is_map_field(left_fd)
                right_is_map = is_map_field(right_fd)
                if left_is_map != right_is_map:
                    left_kind = "map" if left_is_map else "repeated"
                    right_kind = "map" if right_is_map else "repeated"
                    warnings.append(Warning(
                        path=str(field_path),
                        message=f"field changed from {left_kind} to {right_kind}; "
                                "values not compared",
                    ))
                    continue

                # Type compatibility
                if not _types_compatible(left_fd.type, right_fd.type):
                    continue

                # Compare values based on field type
                if left_is_map:
                    self._compare_map(
                        item.left_msg, item.right_msg, left_fd, right_fd,
                        field_path, differences, stack, item.depth,
                        warnings, same_pool,
                    )
                elif left_fd.is_repeated:
                    self._compare_repeated(
                        item.left_msg, item.right_msg, left_fd, right_fd,
                        field_path, differences, stack, item.depth,
                        warnings, same_pool,
                    )
                elif left_fd.type == TYPE_MESSAGE:
                    self._compare_message_field(
                        item.left_msg, item.right_msg, left_fd, right_fd,
                        field_path, stack, item.depth, differences,
                        warnings, same_pool,
                    )
                else:
                    self._compare_leaf(
                        item.left_msg, item.right_msg, left_fd, right_fd,
                        field_path, differences, warnings, same_pool,
                    )

        # Sort results by path for deterministic output
        differences.sort(key=lambda d: str(d.path))

        return DiffResult(
            differences=tuple(differences),
            warnings=tuple(warnings),
            truncated_paths=tuple(truncated_paths),
        )

    # --- Internal methods ---

    def _is_ignored(self, field_name: str, field_path: FieldPath) -> bool:
        """Check if a field should be ignored.

        Args:
            field_name: The bare field name.
            field_path: The fully qualified field path.

        Returns:
            True if the field matches any configured ignore selector.
        """
        if field_name in self._ignore_names:
            return True
        for sel_path in self._ignore_paths:
            # Compare segment names only, ignoring brackets.
            # This ensures "items.name" matches "items[0].name".
            if len(sel_path.segments) == len(field_path.segments) and all(
                s.name == f.name
                for s, f in zip(sel_path.segments, field_path.segments)
            ):
                return True
        return False

    def _check_schema_evolution(
        self,
        left_fd: proto_descriptor.FieldDescriptor,
        right_fd: proto_descriptor.FieldDescriptor,
        path: FieldPath,
        diffs: list[Difference],
        warnings: list[Warning],
    ) -> None:
        """Check for schema evolution between two field descriptors.

        Detects field number changes, type changes, and cardinality changes
        between ``left_fd`` and ``right_fd``, appending any findings to
        ``diffs`` and ``warnings``.

        Args:
            left_fd: Field descriptor from the left message schema.
            right_fd: Field descriptor from the right message schema.
            path: The current field path for reporting.
            diffs: Accumulator list for Difference objects.
            warnings: Accumulator list for Warning objects.
        """
        # Field number change
        if left_fd.number != right_fd.number:
            diffs.append(Difference(
                path=path,
                change_type=ChangeType.FIELD_NUMBER_CHANGED,
                field_type=type_name(left_fd.type),
                left_field_number=left_fd.number,
                right_field_number=right_fd.number,
            ))

        # Type change (skip for message->message)
        if left_fd.type != right_fd.type:
            if not (left_fd.type == TYPE_MESSAGE and right_fd.type == TYPE_MESSAGE):
                diffs.append(Difference(
                    path=path,
                    change_type=ChangeType.TYPE_CHANGED,
                    left_type=type_name(left_fd.type),
                    right_type=type_name(right_fd.type),
                ))

        # Cardinality change
        if left_fd.is_repeated != right_fd.is_repeated:
            diffs.append(Difference(
                path=path,
                change_type=ChangeType.CARDINALITY_CHANGED,
                field_type=type_name(left_fd.type),
                left_label="LABEL_REPEATED" if left_fd.is_repeated else "LABEL_OPTIONAL",
                right_label="LABEL_REPEATED" if right_fd.is_repeated else "LABEL_OPTIONAL",
            ))

        # Strict schema: message type name mismatch warning
        if (
            self.strict_schema
            and left_fd.type == TYPE_MESSAGE
            and right_fd.type == TYPE_MESSAGE
            and left_fd.message_type.full_name != right_fd.message_type.full_name
        ):
            warnings.append(Warning(
                path=str(path),
                message=(
                    f"message type name changed: "
                    f"{left_fd.message_type.full_name} -> "
                    f"{right_fd.message_type.full_name}"
                ),
            ))

    def _compare_leaf(
        self,
        left_msg: Message,
        right_msg: Message,
        left_fd: proto_descriptor.FieldDescriptor,
        right_fd: proto_descriptor.FieldDescriptor,
        path: FieldPath,
        diffs: list[Difference],
        warnings: list[Warning],
        same_pool: bool,
    ) -> None:
        """Compare a leaf (scalar/enum/bytes/float) field.

        Handles presence semantics for proto2/proto3 optional fields and
        delegates value comparison to ``_values_equal``.

        Args:
            left_msg: The left parent message.
            right_msg: The right parent message.
            left_fd: Field descriptor from the left schema.
            right_fd: Field descriptor from the right schema.
            path: The current field path for reporting.
            diffs: Accumulator list for Difference objects.
            warnings: Accumulator list for Warning objects.
            same_pool: True if both messages share a descriptor pool.
        """
        left_val = getattr(left_msg, left_fd.name)
        right_val = getattr(right_msg, right_fd.name)

        # Presence check for proto2/proto3 optional
        left_has = has_presence(left_fd)
        right_has = has_presence(right_fd)

        if left_has and right_has:
            left_present = left_msg.HasField(left_fd.name)
            right_present = right_msg.HasField(right_fd.name)
            if not left_present and not right_present:
                return  # both unset
            if not left_present and right_present:
                diffs.append(Difference(
                    path=path,
                    change_type=ChangeType.ADDED,
                    new_value=self._wrap_value(right_val, right_fd),
                    field_type=type_name(right_fd.type),
                ))
                return
            if left_present and not right_present:
                diffs.append(Difference(
                    path=path,
                    change_type=ChangeType.REMOVED,
                    old_value=self._wrap_value(left_val, left_fd),
                    field_type=type_name(left_fd.type),
                ))
                return
        elif left_has and not right_has:
            # Cross-schema: optional vs non-optional -> value comparison (less restrictive)
            pass
        elif not left_has and right_has:
            pass

        # Value comparison
        equal = self._values_equal(left_val, right_val, left_fd, right_fd, same_pool, warnings, path)
        if not equal:
            diffs.append(Difference(
                path=path,
                change_type=ChangeType.MODIFIED,
                old_value=self._wrap_value(left_val, left_fd),
                new_value=self._wrap_value(right_val, right_fd),
                field_type=type_name(left_fd.type),
            ))

    def _values_equal(
        self,
        left: Any,
        right: Any,
        left_fd: proto_descriptor.FieldDescriptor,
        right_fd: proto_descriptor.FieldDescriptor,
        same_pool: bool,
        warnings: list[Warning],
        path: FieldPath,
    ) -> bool:
        """Compare two field values for equality.

        Dispatches to the appropriate comparator based on field type
        (float, enum, or scalar).

        Args:
            left: The left field value.
            right: The right field value.
            left_fd: Field descriptor from the left schema.
            right_fd: Field descriptor from the right schema.
            same_pool: True if both messages share a descriptor pool.
            warnings: Accumulator list for Warning objects (enum drift).
            path: The current field path for warning context.

        Returns:
            True if the values are considered equal.
        """
        if left_fd.type in (TYPE_FLOAT, TYPE_DOUBLE):
            return compare_float(float(left), float(right), self._float_config)

        if left_fd.type == TYPE_ENUM:
            if same_pool:
                return compare_enum_same_pool(left, right)
            left_ev = to_enum_value(left, left_fd.enum_type)
            right_ev = to_enum_value(right, right_fd.enum_type)
            equal, warning = compare_enum_cross_pool(
                left_ev.number, left_ev.name, right_ev.number, right_ev.name
            )
            if warning:
                warnings.append(Warning(path=str(path), message=warning))
            return equal

        return compare_scalar(left, right)

    def _wrap_value(
        self,
        value: Any,
        fd: proto_descriptor.FieldDescriptor,
    ) -> Any:
        """Wrap a protobuf value for inclusion in a Difference.

        Converts enum integers to EnumValue; passes other types through.

        Args:
            value: The raw protobuf field value.
            fd: The field's descriptor.

        Returns:
            The value, possibly wrapped as an EnumValue.
        """
        if fd.type == TYPE_ENUM:
            return to_enum_value(value, fd.enum_type)
        return value

    def _make_leaf_diff(
        self,
        path: FieldPath,
        change_type: ChangeType,
        value: object,
        fd: proto_descriptor.FieldDescriptor,
        *,
        is_new: bool,
    ) -> Difference:
        """Build a leaf Difference, placing the value in old_value or new_value."""
        wrapped = self._wrap_value(value, fd)
        return Difference(
            path=path,
            change_type=change_type,
            old_value=None if is_new else wrapped,
            new_value=wrapped if is_new else None,
            field_type=type_name(fd.type),
        )

    def _compare_message_field(
        self,
        left_msg: Message,
        right_msg: Message,
        left_fd: proto_descriptor.FieldDescriptor,
        right_fd: proto_descriptor.FieldDescriptor,
        path: FieldPath,
        stack: list[_WorkItem],
        depth: int,
        diffs: list[Difference],
        warnings: list[Warning],
        same_pool: bool,
    ) -> None:
        """Handle singular message field comparison.

        Checks presence on both sides and either emits leaf diffs or
        pushes a _WorkItem onto the stack for recursive comparison.

        Args:
            left_msg: The left parent message.
            right_msg: The right parent message.
            left_fd: Field descriptor from the left schema.
            right_fd: Field descriptor from the right schema.
            path: The current field path.
            stack: The iterative comparison work stack.
            depth: Current comparison depth.
            diffs: Accumulator list for Difference objects.
            warnings: Accumulator list for Warning objects.
            same_pool: True if both messages share a descriptor pool.
        """
        left_present = left_msg.HasField(left_fd.name)
        right_present = right_msg.HasField(right_fd.name)

        if not left_present and not right_present:
            return
        if not left_present and right_present:
            right_child = getattr(right_msg, right_fd.name)
            if _has_populated_fields(right_child):
                stack.append(_WorkItem(None, right_child, path, depth + 1))
            else:
                # Empty-but-present message exception
                diffs.append(Difference(
                    path=path, change_type=ChangeType.ADDED,
                    field_type=type_name(right_fd.type),
                ))
            return
        if left_present and not right_present:
            left_child = getattr(left_msg, left_fd.name)
            if _has_populated_fields(left_child):
                stack.append(_WorkItem(left_child, None, path, depth + 1))
            else:
                diffs.append(Difference(
                    path=path, change_type=ChangeType.REMOVED,
                    field_type=type_name(left_fd.type),
                ))
            return

        # Both present: recurse
        stack.append(_WorkItem(
            getattr(left_msg, left_fd.name),
            getattr(right_msg, right_fd.name),
            path,
            depth + 1,
        ))

    def _compare_repeated(
        self,
        left_msg: Message,
        right_msg: Message,
        left_fd: proto_descriptor.FieldDescriptor,
        right_fd: proto_descriptor.FieldDescriptor,
        path: FieldPath,
        diffs: list[Difference],
        stack: list[_WorkItem],
        depth: int,
        warnings: list[Warning],
        same_pool: bool,
    ) -> None:
        """Compare repeated fields using index-by-index or treat_as_map.

        If ``treat_as_map`` is configured for this field, delegates to
        ``_compare_treat_as_map``. Otherwise compares elements pairwise
        by index and reports extra/missing elements.

        Args:
            left_msg: The left parent message.
            right_msg: The right parent message.
            left_fd: Field descriptor from the left schema.
            right_fd: Field descriptor from the right schema.
            path: The current field path.
            diffs: Accumulator list for Difference objects.
            stack: The iterative comparison work stack.
            depth: Current comparison depth.
            warnings: Accumulator list for Warning objects.
            same_pool: True if both messages share a descriptor pool.
        """
        field_name = left_fd.name

        # Check if treat_as_map is configured for this field
        key_field = self._get_treat_as_map_key(field_name, path)
        if key_field:
            if left_fd.type == TYPE_MESSAGE:
                self._compare_treat_as_map(
                    left_msg, right_msg, left_fd, right_fd, path,
                    key_field, diffs, stack, depth, warnings, same_pool,
                )
                return
            warnings.append(Warning(
                path=str(path),
                message=f"treat_as_map configured but field is not a repeated message "
                        f"(type={type_name(left_fd.type)}); falling back to index comparison",
            ))

        left_list = getattr(left_msg, field_name)
        right_list = getattr(right_msg, field_name)

        min_len = min(len(left_list), len(right_list))

        # Compare pairwise
        for i in range(min_len):
            idx_path = _replace_bracket(path, str(i)) if path.segments else path

            if left_fd.type == TYPE_MESSAGE:
                stack.append(_WorkItem(left_list[i], right_list[i], idx_path, depth + 1))
            else:
                left_val = left_list[i]
                right_val = right_list[i]
                equal = self._values_equal(
                    left_val, right_val, left_fd, right_fd, same_pool, warnings, idx_path
                )
                if not equal:
                    diffs.append(Difference(
                        path=idx_path,
                        change_type=ChangeType.MODIFIED,
                        old_value=self._wrap_value(left_val, left_fd),
                        new_value=self._wrap_value(right_val, right_fd),
                        field_type=type_name(left_fd.type),
                    ))

        # Extra elements
        for i in range(min_len, len(right_list)):
            idx_path = _replace_bracket(path, str(i)) if path.segments else path
            if right_fd.type == TYPE_MESSAGE:
                if _has_populated_fields(right_list[i]):
                    stack.append(_WorkItem(None, right_list[i], idx_path, depth + 1))
                else:
                    diffs.append(Difference(
                        path=idx_path, change_type=ChangeType.ADDED,
                        field_type=type_name(right_fd.type),
                    ))
            else:
                diffs.append(Difference(
                    path=idx_path, change_type=ChangeType.ADDED,
                    new_value=self._wrap_value(right_list[i], right_fd),
                    field_type=type_name(right_fd.type),
                ))

        for i in range(min_len, len(left_list)):
            idx_path = _replace_bracket(path, str(i)) if path.segments else path
            if left_fd.type == TYPE_MESSAGE:
                if _has_populated_fields(left_list[i]):
                    stack.append(_WorkItem(left_list[i], None, idx_path, depth + 1))
                else:
                    diffs.append(Difference(
                        path=idx_path, change_type=ChangeType.REMOVED,
                        field_type=type_name(left_fd.type),
                    ))
            else:
                diffs.append(Difference(
                    path=idx_path, change_type=ChangeType.REMOVED,
                    old_value=self._wrap_value(left_list[i], left_fd),
                    field_type=type_name(left_fd.type),
                ))

    def _compare_map(
        self,
        left_msg: Message,
        right_msg: Message,
        left_fd: proto_descriptor.FieldDescriptor,
        right_fd: proto_descriptor.FieldDescriptor,
        path: FieldPath,
        diffs: list[Difference],
        stack: list[_WorkItem],
        depth: int,
        warnings: list[Warning],
        same_pool: bool,
    ) -> None:
        """Compare native protobuf map fields.

        Iterates over the union of keys from both maps and reports added,
        removed, or modified entries.

        Args:
            left_msg: The left parent message.
            right_msg: The right parent message.
            left_fd: Field descriptor from the left schema.
            right_fd: Field descriptor from the right schema.
            path: The current field path.
            diffs: Accumulator list for Difference objects.
            stack: The iterative comparison work stack.
            depth: Current comparison depth.
            warnings: Accumulator list for Warning objects.
            same_pool: True if both messages share a descriptor pool.
        """
        left_map = getattr(left_msg, left_fd.name)
        right_map = getattr(right_msg, right_fd.name)

        all_keys = left_map.keys() | right_map.keys()
        left_value_fd = left_fd.message_type.fields_by_name["value"]
        right_value_fd = right_fd.message_type.fields_by_name["value"]

        for key in sorted(all_keys, key=lambda k: (type(k).__name__, k)):
            key_str = format_key(key)
            key_path = _replace_bracket(path, key_str) if path.segments else path

            if key not in left_map:
                right_val = right_map[key]
                if right_value_fd.type == TYPE_MESSAGE:
                    if _has_populated_fields(right_val):
                        stack.append(_WorkItem(None, right_val, key_path, depth + 1))
                    else:
                        diffs.append(Difference(
                            path=key_path, change_type=ChangeType.ADDED,
                            field_type=type_name(right_value_fd.type),
                        ))
                else:
                    diffs.append(Difference(
                        path=key_path, change_type=ChangeType.ADDED,
                        new_value=self._wrap_value(right_val, right_value_fd),
                        field_type=type_name(right_value_fd.type),
                    ))
            elif key not in right_map:
                left_val = left_map[key]
                if left_value_fd.type == TYPE_MESSAGE:
                    if _has_populated_fields(left_val):
                        stack.append(_WorkItem(left_val, None, key_path, depth + 1))
                    else:
                        diffs.append(Difference(
                            path=key_path, change_type=ChangeType.REMOVED,
                            field_type=type_name(left_value_fd.type),
                        ))
                else:
                    diffs.append(Difference(
                        path=key_path, change_type=ChangeType.REMOVED,
                        old_value=self._wrap_value(left_val, left_value_fd),
                        field_type=type_name(left_value_fd.type),
                    ))
            else:
                # Both have the key
                if left_value_fd.type == TYPE_MESSAGE:
                    stack.append(_WorkItem(
                        left_map[key], right_map[key], key_path, depth + 1,
                    ))
                else:
                    equal = self._values_equal(
                        left_map[key], right_map[key],
                        left_value_fd, right_value_fd,
                        same_pool, warnings, key_path,
                    )
                    if not equal:
                        diffs.append(Difference(
                            path=key_path,
                            change_type=ChangeType.MODIFIED,
                            old_value=self._wrap_value(left_map[key], left_value_fd),
                            new_value=self._wrap_value(right_map[key], right_value_fd),
                            field_type=type_name(left_value_fd.type),
                        ))

    def _compare_treat_as_map(
        self,
        left_msg: Message,
        right_msg: Message,
        left_fd: proto_descriptor.FieldDescriptor,
        right_fd: proto_descriptor.FieldDescriptor,
        path: FieldPath,
        key_field_name: str,
        diffs: list[Difference],
        stack: list[_WorkItem],
        depth: int,
        warnings: list[Warning],
        same_pool: bool,
    ) -> None:
        """Compare a repeated message field using key-based matching.

        Elements are matched by extracting the configured key sub-field
        from each element. Unmatched keys are reported as added or removed.

        Args:
            left_msg: The left parent message.
            right_msg: The right parent message.
            left_fd: Field descriptor from the left schema.
            right_fd: Field descriptor from the right schema.
            path: The current field path.
            key_field_name: Name of the sub-field used as the map key.
            diffs: Accumulator list for Difference objects.
            stack: The iterative comparison work stack.
            depth: Current comparison depth.
            warnings: Accumulator list for Warning objects.
            same_pool: True if both messages share a descriptor pool.
        """
        left_list = getattr(left_msg, left_fd.name)
        right_list = getattr(right_msg, right_fd.name)

        left_by_key = self._extract_keys(left_list, key_field_name, left_fd, path)
        right_by_key = self._extract_keys(right_list, key_field_name, right_fd, path)

        all_keys = left_by_key.keys() | right_by_key.keys()

        for key in sorted(all_keys, key=lambda k: (type(k).__name__, str(k))):
            key_bracket = f"{key_field_name}={format_key(key)}"
            key_path = _replace_bracket(path, key_bracket) if path.segments else path

            if key not in left_by_key:
                right_elem = right_by_key[key]
                if _has_populated_fields(right_elem):
                    stack.append(_WorkItem(None, right_elem, key_path, depth + 1))
                else:
                    diffs.append(Difference(
                        path=key_path, change_type=ChangeType.ADDED,
                        field_type=type_name(right_fd.type),
                    ))
            elif key not in right_by_key:
                left_elem = left_by_key[key]
                if _has_populated_fields(left_elem):
                    stack.append(_WorkItem(left_elem, None, key_path, depth + 1))
                else:
                    diffs.append(Difference(
                        path=key_path, change_type=ChangeType.REMOVED,
                        field_type=type_name(left_fd.type),
                    ))
            else:
                stack.append(_WorkItem(
                    left_by_key[key], right_by_key[key], key_path, depth + 1,
                ))

    def _extract_keys(
        self,
        elements: Any,
        key_field_name: str,
        fd: proto_descriptor.FieldDescriptor,
        path: FieldPath,
    ) -> dict[Any, Message]:
        """Extract key values from repeated message elements.

        Args:
            elements: Iterable of protobuf Message elements.
            key_field_name: Name of the sub-field to use as key.
            fd: Field descriptor of the repeated field.
            path: The current field path (for error messages).

        Returns:
            A dict mapping each key value to its message element.

        Raises:
            ValueError: If the key field is not found in the descriptor.
            MissingKeyError: If an element is missing the key field.
            DuplicateKeyError: If two elements share the same key value.
        """
        result: dict[Any, Message] = {}
        key_fd = fd.message_type.fields_by_name.get(key_field_name)
        if key_fd is None:
            raise ValueError(
                f"key field '{key_field_name}' not found in descriptor "
                f"for {fd.message_type.full_name}"
            )

        for elem in elements:
            # Check presence for proto2/proto3 optional
            if has_presence(key_fd) and not elem.HasField(key_field_name):
                raise MissingKeyError(
                    f"Element in '{str(path)}' is missing key field '{key_field_name}'"
                )
            key_val = getattr(elem, key_field_name)
            if key_val in result:
                raise DuplicateKeyError(
                    f"Duplicate key '{key_val}' in '{str(path)}' "
                    f"for key field '{key_field_name}'"
                )
            result[key_val] = elem
        return result

    def _get_treat_as_map_key(self, field_name: str, field_path: FieldPath) -> str | None:
        """Get the key field name if treat_as_map is configured for this field.

        Checks path-scoped selectors first (bracket-stripped), then bare name.

        Args:
            field_name: The bare field name.
            field_path: The fully qualified field path.

        Returns:
            The key field name if configured, otherwise ``None``.
        """
        # Check path-scoped first (bracket-stripped segment name comparison),
        # then bare name
        for sel_path, key in self._treat_as_map_paths:
            if len(sel_path.segments) == len(field_path.segments) and all(
                s.name == f.name
                for s, f in zip(sel_path.segments, field_path.segments)
            ):
                return key
        if field_name in self._treat_as_map:
            return self._treat_as_map[field_name]
        return None

    def _emit_all_fields(
        self,
        msg: Message,
        path: FieldPath,
        change_type: ChangeType,
        diffs: list[Difference],
        *,
        is_new: bool,
        depth: int = 0,
        warnings: list[Warning] | None = None,
        truncated_paths: list[FieldPath] | None = None,
    ) -> None:
        """Emit leaf-level diffs for all populated fields in a message.

        Used when an entire sub-message is added or removed, to report
        each populated leaf as its own Difference.

        Args:
            msg: The protobuf Message whose fields to emit.
            path: The path prefix for the emitted differences.
            change_type: ``ChangeType.ADDED`` or ``ChangeType.REMOVED``.
            diffs: Accumulator list for Difference objects.
            is_new: If True, values go into ``new_value``; otherwise
                ``old_value``.
            depth: Current comparison depth for max_depth enforcement.
            warnings: Accumulator list for Warning objects (truncation).
            truncated_paths: Accumulator list for truncated FieldPaths.
        """
        # Use an internal stack to handle arbitrary nesting depth.
        # Each entry: (message, path, depth)
        emit_stack: list[tuple[Message, FieldPath, int]] = [(msg, path, depth)]

        while emit_stack:
            cur_msg, cur_path, cur_depth = emit_stack.pop()

            # Max depth check
            if self.max_depth is not None and cur_depth > self.max_depth:
                if truncated_paths is not None:
                    truncated_paths.append(cur_path)
                if warnings is not None:
                    warnings.append(Warning(
                        path=str(cur_path) if cur_path else None,
                        message=f"comparison truncated at depth {self.max_depth}; "
                                "differences below this path are not reported",
                    ))
                continue

            populated = cur_msg.ListFields()
            if not populated:
                # Empty-but-present message exception
                diffs.append(Difference(path=cur_path, change_type=change_type))
                continue

            for fd, value in populated:
                if fd.is_extension:
                    continue
                field_path = cur_path.child(fd.name)

                # Respect ignore_fields
                if self._is_ignored(fd.name, field_path):
                    continue

                if is_map_field(fd):
                    # Native map field: iterate entries
                    value_fd = fd.message_type.fields_by_name["value"]
                    for k, v in value.items():
                        key_str = format_key(k)
                        key_path = _replace_bracket(field_path, key_str)
                        if value_fd.type == TYPE_MESSAGE:
                            if _has_populated_fields(v):
                                emit_stack.append((v, key_path, cur_depth + 1))
                            else:
                                diffs.append(Difference(
                                    path=key_path, change_type=change_type,
                                    field_type=type_name(value_fd.type),
                                ))
                        else:
                            diffs.append(self._make_leaf_diff(
                                key_path, change_type, v, value_fd, is_new=is_new,
                            ))
                elif fd.type == TYPE_MESSAGE and not fd.is_repeated:
                    # Singular sub-message: push for full recursion
                    emit_stack.append((value, field_path, cur_depth + 1))
                elif fd.is_repeated:
                    # Check treat_as_map for key-based path formatting
                    tam_key = (
                        self._get_treat_as_map_key(fd.name, field_path)
                        if fd.type == TYPE_MESSAGE
                        else None
                    )
                    # Look up the key field descriptor once for the whole list
                    tam_key_fd = (
                        fd.message_type.fields_by_name.get(tam_key)
                        if tam_key
                        else None
                    )
                    for i, elem in enumerate(value):
                        if tam_key_fd and fd.type == TYPE_MESSAGE:
                            # Use presence-aware check consistent with _extract_keys
                            if not has_presence(tam_key_fd) or elem.HasField(tam_key):
                                key_val = getattr(elem, tam_key)
                                key_bracket = f"{tam_key}={format_key(key_val)}"
                            else:
                                key_bracket = str(i)
                            elem_path = _replace_bracket(field_path, key_bracket)
                        else:
                            elem_path = _replace_bracket(field_path, str(i))
                        if fd.type == TYPE_MESSAGE:
                            if _has_populated_fields(elem):
                                emit_stack.append((elem, elem_path, cur_depth + 1))
                            else:
                                diffs.append(Difference(
                                    path=elem_path, change_type=change_type,
                                    field_type=type_name(fd.type),
                                ))
                        else:
                            diffs.append(self._make_leaf_diff(
                                elem_path, change_type, elem, fd, is_new=is_new,
                            ))
                else:
                    diffs.append(self._make_leaf_diff(
                        field_path, change_type, value, fd, is_new=is_new,
                    ))

    def _emit_one_sided(
        self,
        msg: Message,
        fd: proto_descriptor.FieldDescriptor,
        path: FieldPath,
        diffs: list[Difference],
        stack: list[_WorkItem],
        depth: int,
        *,
        is_new: bool,
    ) -> None:
        """Handle a field that only exists on one side (ADDED or REMOVED).

        Args:
            msg: The parent message containing the field.
            fd: Field descriptor for the one-sided field.
            path: The current field path.
            diffs: Accumulator list for Difference objects.
            stack: The iterative comparison work stack.
            depth: Current comparison depth.
            is_new: True for ADDED (right-only), False for REMOVED (left-only).
        """
        change_type = ChangeType.ADDED if is_new else ChangeType.REMOVED

        def _work_item(child: Message, p: FieldPath) -> _WorkItem:
            if is_new:
                return _WorkItem(None, child, p, depth + 1)
            return _WorkItem(child, None, p, depth + 1)

        if fd.type == TYPE_MESSAGE and not fd.is_repeated:
            if msg.HasField(fd.name):
                child = getattr(msg, fd.name)
                if _has_populated_fields(child):
                    stack.append(_work_item(child, path))
                else:
                    diffs.append(Difference(
                        path=path, change_type=change_type,
                        field_type=type_name(fd.type),
                    ))
        elif is_map_field(fd):
            map_val = getattr(msg, fd.name)
            value_fd = fd.message_type.fields_by_name["value"]
            for k, v in map_val.items():
                key_str = format_key(k)
                key_path = _replace_bracket(path, key_str) if path.segments else path
                if value_fd.type == TYPE_MESSAGE:
                    if _has_populated_fields(v):
                        stack.append(_work_item(v, key_path))
                    else:
                        diffs.append(Difference(
                            path=key_path, change_type=change_type,
                            field_type=type_name(value_fd.type),
                        ))
                else:
                    diffs.append(self._make_leaf_diff(
                        key_path, change_type, v, value_fd, is_new=is_new,
                    ))
        elif fd.is_repeated:
            vals = getattr(msg, fd.name)
            for i, elem in enumerate(vals):
                idx_path = _replace_bracket(path, str(i)) if path.segments else path
                if fd.type == TYPE_MESSAGE:
                    if _has_populated_fields(elem):
                        stack.append(_work_item(elem, idx_path))
                    else:
                        diffs.append(Difference(
                            path=idx_path, change_type=change_type,
                            field_type=type_name(fd.type),
                        ))
                else:
                    diffs.append(self._make_leaf_diff(
                        idx_path, change_type, elem, fd, is_new=is_new,
                    ))
        else:
            val = getattr(msg, fd.name)
            # Skip unset fields: use HasField for presence-aware fields,
            # default-value check for proto3 implicit-presence fields
            if has_presence(fd):
                if not msg.HasField(fd.name):
                    return
            elif val == fd.default_value:
                return
            diffs.append(self._make_leaf_diff(
                path, change_type, val, fd, is_new=is_new,
            ))


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _has_populated_fields(msg: Message) -> bool:
    """Check if a message has any populated fields.

    Args:
        msg: A protobuf Message.

    Returns:
        True if ``msg.ListFields()`` is non-empty.
    """
    return bool(msg.ListFields())


# ---------------------------------------------------------------------------
# Public API convenience function
# ---------------------------------------------------------------------------


def diff_messages(
    left: Message,
    right: Message,
    *,
    max_depth: int | None = None,
    strict_schema: bool = False,
) -> DiffResult:
    """Compare two protobuf messages and return a DiffResult.

    Convenience function that creates a MessageDifferencer with the given options.

    Args:
        left: The left-side protobuf ``Message`` (old/expected).
        right: The right-side protobuf ``Message`` (new/actual).
        max_depth: Maximum comparison depth. ``None`` (the default)
            means unlimited; subtrees below the limit are not
            compared and their paths appear in
            ``DiffResult.truncated_paths``.
        strict_schema: When True, emit a ``Warning`` if the two
            messages have different fully-qualified type names.
            Defaults to False.

    Returns:
        A ``DiffResult`` with differences, warnings, and truncation
        markers. Differences are sorted by path.

    Raises:
        DuplicateKeyError: If ``treat_as_map`` were configured on
            the differencer (not possible via this convenience
            function; use ``MessageDifferencer`` directly).
    """
    differ = MessageDifferencer()
    if max_depth is not None:
        differ.max_depth = max_depth
    differ.strict_schema = strict_schema
    return differ.compare(left, right)
