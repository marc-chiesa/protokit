"""Comment-access helpers for option-aware lint rules.

Bridges :attr:`protokit.schema.compile.CompileResult.source_info_descriptors`
to rule bodies that need to read proto-source comments — currently the
R6 deprecated-replacement rule family.

Two module-level free functions:

* :func:`descriptor_path` — encode a descriptor as the
  ``source_code_info.location[].path`` ``tuple[int, ...]`` coordinates.
  Dispatches across ``FieldDescriptor``, ``EnumValueDescriptor``,
  ``MethodDescriptor``, ``Descriptor`` (message), and ``EnumDescriptor``.
  Handles both top-level and nested cases by walking the descriptor's
  parent chain (``containing_type``, ``containing_service``, ``type``).
* :func:`leading_comment` — leaf lookup that walks a
  ``FileDescriptorProto``'s ``source_code_info.location[]`` for the
  ``Location`` whose ``path`` matches, returning the stripped
  ``leading_comments`` or ``None`` for every shape of missing data.

The two helpers are split to keep concerns isolated:
``descriptor_path`` is pure descriptor introspection (no source-info
mapping involved); ``leading_comment`` is pure mapping lookup (no
descriptor introspection). Each is independently unit-testable; their
co-location keeps the U3 callers' import surface single-line:

    from protokit.schema.lint.rules.options._comments import (
        descriptor_path, leading_comment,
    )
    path = descriptor_path(ctx.field)
    comment = leading_comment(ctx.source_info_descriptors, ctx.file.name, path)

**Cold-import contract.** This module sits under
``protokit.schema.lint.rules.options.*`` — already a lazy-load subtree
per the rule-pack discipline. The ``FileDescriptorProto`` annotation is
TYPE_CHECKING-guarded so importing this module does NOT pull in the
``descriptor_pb2`` module weight (~8 additional protobuf modules). The
``google.protobuf.descriptor`` runtime import is unavoidable for the
``isinstance`` dispatch in :func:`descriptor_path`, but it is already
imported by every lint context site so the runtime cost is already paid.

**Wire-tag numbers.** The integer constants (``4``/``5``/``6`` at file
level, ``2``/``3``/``4`` inside containers) come from ``descriptor.proto``
and are a stable contract across protobuf 4 and 5:

* ``FileDescriptorProto.message_type`` = 4
* ``FileDescriptorProto.enum_type`` = 5
* ``FileDescriptorProto.service`` = 6
* ``DescriptorProto.field`` = 2
* ``DescriptorProto.nested_type`` = 3
* ``DescriptorProto.enum_type`` = 4
* ``EnumDescriptorProto.value`` = 2
* ``ServiceDescriptorProto.method`` = 2

See the leading-comment helper recipe table in the project's design
notes for the full encoding.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from google.protobuf import descriptor as proto_descriptor

if TYPE_CHECKING:
    # TYPE_CHECKING-guarded to keep ``descriptor_pb2`` (and its ~8
    # transitive protobuf modules) off the module-import cost path
    # per K-3. Annotation is a string under ``from __future__ import
    # annotations`` so this import never resolves at runtime.
    from google.protobuf.descriptor_pb2 import FileDescriptorProto


# Wire-tag constants from descriptor.proto. Named for readability; the
# call sites below reference them inline so a future reader doesn't have
# to chase the integer back to the proto definition.
_FILE_MESSAGE_TYPE_TAG = 4
"""``FileDescriptorProto.message_type`` field number."""

_FILE_ENUM_TYPE_TAG = 5
"""``FileDescriptorProto.enum_type`` field number."""

_FILE_SERVICE_TAG = 6
"""``FileDescriptorProto.service`` field number."""

_MESSAGE_FIELD_TAG = 2
"""``DescriptorProto.field`` field number."""

_MESSAGE_NESTED_TYPE_TAG = 3
"""``DescriptorProto.nested_type`` field number."""

_MESSAGE_ENUM_TYPE_TAG = 4
"""``DescriptorProto.enum_type`` field number."""

_ENUM_VALUE_TAG = 2
"""``EnumDescriptorProto.value`` field number."""

_SERVICE_METHOD_TAG = 2
"""``ServiceDescriptorProto.method`` field number."""


def descriptor_path(descriptor: object) -> tuple[int, ...]:
    """Encode ``descriptor`` as ``source_code_info.location[].path`` coordinates.

    Dispatches on descriptor type and walks the parent chain to compute
    the descriptor-graph coordinates the protobuf compiler emits into
    ``source_code_info.location[].path`` for the descriptor's defining
    syntactic element.

    The supported descriptor types match the 5 R6 ElementKind contexts
    (``FieldDescriptor``, ``EnumValueDescriptor``, ``MethodDescriptor``,
    ``Descriptor`` for messages, ``EnumDescriptor``). The recipe (per
    plan K-5):

    +-----------------------------+-----------------------------------------+
    | Descriptor type             | Path recipe                             |
    +=============================+=========================================+
    | ``Descriptor`` (top-level)  | ``(4, msg_index_in_file)``              |
    +-----------------------------+-----------------------------------------+
    | ``Descriptor`` (nested)     | ``parent_msg_path + (3, nested_index)`` |
    +-----------------------------+-----------------------------------------+
    | ``FieldDescriptor``         | ``msg_path + (2, field_index_in_msg)``  |
    +-----------------------------+-----------------------------------------+
    | ``EnumDescriptor`` (file)   | ``(5, enum_index_in_file)``             |
    +-----------------------------+-----------------------------------------+
    | ``EnumDescriptor`` (nested) | ``parent_msg_path + (4, enum_index)``   |
    +-----------------------------+-----------------------------------------+
    | ``EnumValueDescriptor``     | ``enum_path + (2, value_index)``        |
    +-----------------------------+-----------------------------------------+
    | ``MethodDescriptor``        | ``(6, svc_index, 2, method_index)``     |
    +-----------------------------+-----------------------------------------+

    Args:
        descriptor: One of the 5 protobuf descriptor types listed above.

    Returns:
        The path tuple. Always non-empty; the first integer is the
        file-level wire tag (``4``/``5``/``6``).

    Raises:
        TypeError: If ``descriptor`` is not one of the 5 supported types.
            Reachable only via programmer error (passing a service or
            oneof descriptor, or a non-descriptor object). Unsupported
            descriptor types are out of scope by design — see the plan's
            K-2 / Scope Boundaries for the 5-context-only YAGNI bound.
    """
    # ``isinstance`` dispatch — order matters because ``EnumValueDescriptor``
    # and ``MethodDescriptor`` carry an ``.index`` attribute while
    # ``Descriptor`` (message) and ``EnumDescriptor`` do not, so the
    # walk-the-collection path is reserved for the latter two.
    if isinstance(descriptor, proto_descriptor.FieldDescriptor):
        msg = descriptor.containing_type
        return descriptor_path(msg) + (_MESSAGE_FIELD_TAG, descriptor.index)

    if isinstance(descriptor, proto_descriptor.EnumValueDescriptor):
        enum = descriptor.type
        return descriptor_path(enum) + (_ENUM_VALUE_TAG, descriptor.index)

    if isinstance(descriptor, proto_descriptor.MethodDescriptor):
        svc = descriptor.containing_service
        return (
            _FILE_SERVICE_TAG, svc.index,
            _SERVICE_METHOD_TAG, descriptor.index,
        )

    if isinstance(descriptor, proto_descriptor.Descriptor):
        parent = descriptor.containing_type
        if parent is None:
            file = descriptor.file
            # ``message_types_by_name`` is a dict that preserves declaration
            # order (Python 3.7+ dict insertion order; protobuf populates it
            # in DescriptorProto.message_type wire order). ``.index(obj)``
            # finds the matching descriptor by equality, which for the
            # singleton descriptor objects in a DescriptorPool is identity.
            siblings = list(file.message_types_by_name.values())
            return (_FILE_MESSAGE_TYPE_TAG, siblings.index(descriptor))
        # Nested message — recurse into parent then add (3, nested_index).
        siblings = list(parent.nested_types_by_name.values())
        return descriptor_path(parent) + (
            _MESSAGE_NESTED_TYPE_TAG, siblings.index(descriptor),
        )

    if isinstance(descriptor, proto_descriptor.EnumDescriptor):
        parent = descriptor.containing_type
        if parent is None:
            file = descriptor.file
            siblings = list(file.enum_types_by_name.values())
            return (_FILE_ENUM_TYPE_TAG, siblings.index(descriptor))
        # Nested enum — recurse into parent message then add (4, enum_index).
        siblings = list(parent.enum_types_by_name.values())
        return descriptor_path(parent) + (
            _MESSAGE_ENUM_TYPE_TAG, siblings.index(descriptor),
        )

    raise TypeError(
        f"descriptor_path() got unsupported descriptor type "
        f"{type(descriptor).__name__!r}; supported types are "
        "FieldDescriptor, EnumValueDescriptor, MethodDescriptor, "
        "Descriptor (message), and EnumDescriptor"
    )


def leading_comment(
    source_info_descriptors: Mapping[str, FileDescriptorProto] | None,
    file_name: str,
    path: tuple[int, ...],
) -> str | None:
    """Look up the leading comment for the given descriptor ``path``.

    Walks ``source_info_descriptors[file_name].source_code_info.location[]``
    for the first ``Location`` whose ``path`` matches ``path`` exactly
    (literal-tuple equality, no fuzzy or prefix matching), then returns
    ``Location.leading_comments`` stripped of leading and trailing
    whitespace, or ``None`` when the stripped result is empty.

    **Return value is UNSANITIZED.** Control characters (U+0000-U+001F),
    line separators (U+2028, U+2029), and other adversarial code points
    in proto source comments are preserved verbatim — only formatting
    whitespace is normalized via ``.strip()``. Callers emitting the
    return value into wire-format output (lint findings, JSON, SARIF,
    JUnit ``<system-out>``) MUST run it through the existing
    ``protokit.schema.lint._cli_utils._safe_for_stderr`` sanitizer (or
    equivalent) first. The dual-sanitization model is enforced at
    finding-construction time by callers, not here.

    **Legitimate ``None`` state.** ``source_info_descriptors`` is ``None``
    whenever the caller did NOT pass ``include_source_info=True`` into
    ``compile_protos_to_result``. Comment-aware lint rules (the U3 R6
    family) will treat the ``None`` return as "no comment found" and
    emit findings accordingly per the brainstorm + parent-plan accepted
    tradeoff (K-6). Programmatic callers wanting accurate R6 results
    must opt in.

    Args:
        source_info_descriptors: The mapping from ``CompileResult.source_info_descriptors``,
            or ``None`` when the caller did not opt into preserving
            ``source_code_info``.
        file_name: The proto file name as it appears on the matching
            ``FileDescriptor.name`` (e.g., ``"demo.proto"``). This is
            the LITERAL POSIX-separator path the user passed to the
            compiler — no ``Path.resolve()`` or normalization is applied
            on either side of the lookup.
        path: The descriptor-graph coordinates from :func:`descriptor_path`.
            Any iterable of ints is accepted; the helper normalizes to a
            tuple before comparison.

    Returns:
        The stripped ``leading_comments`` string when a matching
        ``Location`` exists and its ``leading_comments`` is non-empty
        after stripping. ``None`` otherwise — for any of:

        * ``source_info_descriptors`` is ``None``
        * ``file_name`` not in the mapping
        * no ``Location`` matches ``path``
        * the matched ``Location.leading_comments`` is empty or
          whitespace-only after ``.strip()``
    """
    if source_info_descriptors is None:
        return None
    fd_proto = source_info_descriptors.get(file_name)
    if fd_proto is None:
        return None
    target = tuple(path)
    for loc in fd_proto.source_code_info.location:
        if tuple(loc.path) == target:
            text = loc.leading_comments.strip()
            return text if text else None
    return None
