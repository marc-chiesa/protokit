"""``compile_fields`` — the ``--fields`` selection compiler (internal).

Validates a comma-separated list of dotted field paths against a message
descriptor and returns an ordered, validated :class:`CompiledSelection` that the
render-time projection layer (a later unit) consumes to prune a dense
``MessageToDict(...)`` output down to the selected fields.

This is the field-selection twin of :mod:`protokit.storage._where`'s
``compile_where``: it mirrors that module's compile-once discipline, its
``_walk_path``-style descriptor walk (reusing the same
:mod:`protokit._descriptors` helpers), and its typed-error shape
(:class:`FieldSelectionError` is to ``--fields`` what ``WhereError`` is to
``--where``). Two deliberate divergences from ``_where`` (per the plan, KTD3):

- **Any terminal kind is allowed.** A ``--fields`` path names a *selection
  target*, not a comparison leaf, so the terminal segment may be a scalar, a
  singular submessage, a repeated or map field, or a ``oneof`` member. This
  module therefore does **not** port ``_where``'s ``_reject_uncomparable_terminal``.
- **It returns data, not a predicate.** ``compile_where`` returns a
  ``Callable[[Message], bool]``; ``compile_fields`` returns a
  :class:`CompiledSelection` describing which field-name chains to keep.

Non-terminal segments still follow ``_where``'s descent rule: each must be a
singular submessage (it has a ``message_type`` and is neither repeated nor a
map), since R2 forbids descending into repeated/map *elements*. Empty specs,
empty paths, empty or non-identifier segments, and unknown field names are all
rejected up front with the sorted available-field-names message, exactly like
``_where``.

This module is internal (``--fields`` is CLI sugar). U2 owns the public
projection helper and the ``__all__`` export of :class:`FieldSelectionError`.
"""

from __future__ import annotations

from dataclasses import dataclass

from google.protobuf import descriptor as _d

from protokit import _descriptors
from protokit.storage.source import StorageError


@dataclass(frozen=True)
class CompiledSelection:
    """A validated, ordered ``--fields`` selection.

    The projection layer (U2) consumes this to prune a dense
    ``json_format.MessageToDict(message, ..., preserving_proto_field_name=True)``
    output — a dict whose keys are snake_case proto field names — down to the
    selected paths.

    Attributes:
        paths: One tuple per ``--fields`` path, in the order the paths were
            given. Each inner tuple is the chain of **snake_case field-name
            segments** (each matching the corresponding descriptor ``fd.name``),
            so a path maps directly to a nested-key descent over the
            ``preserving_proto_field_name=True`` dict. Every non-terminal
            segment is guaranteed to be a singular submessage key (R2 forbids
            descent into repeated/map elements), so the descent is a simple
            nested-key walk. The terminal segment may name any field kind.
    """

    paths: tuple[tuple[str, ...], ...]


class FieldSelectionError(StorageError):
    """A ``--fields`` selection could not be compiled.

    A typed library exception (a :class:`StorageError`) so a CLI layer catches
    it and translates to an exit code; the message names the offending path and,
    for an unknown field, lists the sorted available field names. Mirrors
    :class:`protokit.storage._where.WhereError`'s shape.

    Attributes:
        spec: The original ``--fields`` spec that failed.
        reason: A human-readable explanation.
    """

    def __init__(self, spec: str, reason: str) -> None:
        self.spec = spec
        self.reason = reason
        super().__init__(f"invalid --fields selection {spec!r}: {reason}")


def compile_fields(spec: str, descriptor: _d.Descriptor) -> CompiledSelection:
    """Compile ``spec`` against ``descriptor`` into a validated selection.

    Args:
        spec: A comma-separated list of dotted field paths, e.g.
            ``"name, header.code, labels"``.
        descriptor: The ``Descriptor`` of the message the selection applies to
            (e.g. ``message_class.DESCRIPTOR``).

    Returns:
        A :class:`CompiledSelection` whose ``paths`` preserve the given order and
        carry the snake_case field-name chain for each path.

    Raises:
        FieldSelectionError: the spec is empty, a path is empty, a segment is
            empty or not a valid identifier, a field name is unknown, or a
            non-terminal segment descends into a repeated/map field or a scalar.
    """
    if not spec.strip():
        raise FieldSelectionError(spec, "empty selection")

    paths: list[tuple[str, ...]] = []
    for raw_path in spec.split(","):
        path_str = raw_path.strip()
        if not path_str:
            raise FieldSelectionError(spec, "empty field path")
        fields = _walk_path(path_str, descriptor, spec)
        paths.append(tuple(fd.name for fd in fields))
    return CompiledSelection(paths=tuple(paths))


def _walk_path(
    path_str: str, descriptor: _d.Descriptor, spec: str
) -> list[_d.FieldDescriptor]:
    """Validate a dotted path against ``descriptor`` -> the field chain.

    Each non-terminal segment must be a singular submessage (so it can be
    descended into); the terminal segment may be any field kind. An unknown
    segment lists the sorted available field names. Mirrors
    ``_where._walk_path``, minus the terminal-kind rejection.
    """
    segments = path_str.split(".")
    fields: list[_d.FieldDescriptor] = []
    current = descriptor
    for idx, seg in enumerate(segments):
        if not seg:
            raise FieldSelectionError(spec, f"empty path segment in {path_str!r}")
        if not seg.isidentifier():
            raise FieldSelectionError(spec, f"invalid field-path segment {seg!r}")
        field_map = _descriptors.get_field_map(current)
        fd = field_map.get(seg)
        if fd is None:
            available = ", ".join(sorted(field_map)) or "(none)"
            raise FieldSelectionError(
                spec,
                f"no field {seg!r} on {current.full_name} (available: {available})",
            )
        fields.append(fd)
        if idx != len(segments) - 1:  # not the terminal -> must be descendable
            if _descriptors.is_repeated(fd) or _descriptors.is_map_field(fd):
                raise FieldSelectionError(
                    spec, f"cannot descend into repeated/map field {seg!r}"
                )
            if fd.message_type is None:
                raise FieldSelectionError(
                    spec, f"cannot descend into scalar field {seg!r}"
                )
            # Typed local to satisfy mypy --strict warn_return_any (descriptor
            # attributes are Any because the protobuf stubs are ignored).
            next_descriptor: _d.Descriptor = fd.message_type
            current = next_descriptor
    return fields
