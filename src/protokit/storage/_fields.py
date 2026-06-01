"""``--fields`` selection: the compiler, the projection, and the fill shim.

``compile_fields`` (internal) validates a comma-separated list of dotted field
paths against a message descriptor and returns an ordered, validated
:class:`CompiledSelection`. :func:`project` (public) consumes that selection to
prune a dense ``MessageToDict(...)`` render down to the selected fields, yielding
the faithful nested view. :func:`no_presence_kwarg` (and the
:data:`NO_PRESENCE_FILL_KWARG` constant it returns) is the KTD2 cross-version
shim that picks the right no-presence-fill keyword for the installed protobuf;
U4's ``--explicit-defaults`` reuses it rather than re-detecting.

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

``compile_fields`` and :class:`CompiledSelection` stay internal (``--fields`` is
CLI sugar, mirroring how ``compile_where`` is internal); only :func:`project` and
:class:`FieldSelectionError` are exported from ``protokit.storage`` (R11/R12 —
library parity without widening the engine contract).
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any

from google.protobuf import descriptor as _d
from google.protobuf import json_format
from google.protobuf.message import Message

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


# --- no-presence-fill kwarg shim (KTD2) -----------------------------------
#
# The ``json_format.MessageToDict``/``MessageToJson`` keyword that fills
# no-presence fields at their default was renamed across the pinned
# ``protobuf>=4.21.0,<6`` range:
#
#   - ``including_default_value_fields`` — protobuf 4.21 .. 5.26 (old name).
#   - ``always_print_fields_with_no_presence`` — protobuf 5.27+ (new name).
#
# On 5.27+ the old name raises ``TypeError`` (verified on 5.27.5), and using the
# old, deprecated name on 5.27+ would emit a ``DeprecationWarning`` that
# strict-warning CI promotes to an error (see the
# ``deprecationwarning-poisons-except-exception`` learning). We therefore detect
# the supported kwarg *once* by inspecting the signature and **prefer the new
# name**. This single source of truth is reused by U4's ``--explicit-defaults``
# render so it never re-implements the detection.

_NEW_NO_PRESENCE_KWARG = "always_print_fields_with_no_presence"
_OLD_NO_PRESENCE_KWARG = "including_default_value_fields"


def _detect_no_presence_kwarg() -> str:
    """Return the no-presence-fill kwarg the installed protobuf accepts.

    Inspects ``json_format.MessageToDict``'s signature once and prefers the new
    name (:data:`_NEW_NO_PRESENCE_KWARG`) so a 5.27+ runtime never sees the
    deprecated old name (which would emit a ``DeprecationWarning`` that
    strict-warning CI promotes to an error).

    Raises:
        RuntimeError: the installed protobuf exposes neither kwarg (outside the
            pinned ``>=4.21.0,<6`` range — the KTD2 worst-case fallback).
    """
    params = inspect.signature(json_format.MessageToDict).parameters
    if _NEW_NO_PRESENCE_KWARG in params:
        return _NEW_NO_PRESENCE_KWARG
    if _OLD_NO_PRESENCE_KWARG in params:
        return _OLD_NO_PRESENCE_KWARG
    raise RuntimeError(  # pragma: no cover - outside the pinned protobuf range
        "json_format.MessageToDict exposes neither "
        f"{_NEW_NO_PRESENCE_KWARG!r} nor {_OLD_NO_PRESENCE_KWARG!r}; "
        "the installed protobuf is outside the supported >=4.21.0,<6 range"
    )


#: The no-presence-fill kwarg name resolved once at import (KTD2). U2's
#: :func:`project` and U4's ``--explicit-defaults`` render both pass this as a
#: keyword to ``MessageToDict``/``MessageToJson`` (``{no_presence_kwarg(): True}``)
#: so neither re-implements the cross-version detection.
NO_PRESENCE_FILL_KWARG = _detect_no_presence_kwarg()


def no_presence_kwarg() -> str:
    """Return the no-presence-fill kwarg name for the installed protobuf.

    A thin accessor over :data:`NO_PRESENCE_FILL_KWARG` (resolved once at import
    via :func:`_detect_no_presence_kwarg`). Callers fill no-presence fields with
    ``MessageToDict(msg, **{no_presence_kwarg(): True}, ...)``. Exposed so U4's
    ``--explicit-defaults`` reuses the exact same detection rather than
    duplicating the cross-version logic (KTD2).
    """
    return NO_PRESENCE_FILL_KWARG


# --- projection (KTD1: render-dense-then-prune-the-dict) -------------------


def project(message: Message, selection: CompiledSelection) -> dict[str, Any]:
    """Project ``message`` onto ``selection`` -> a faithful nested ``dict``.

    The crux of ``--fields`` (KTD1). Renders ``message`` to a *dense* dict via
    ``json_format.MessageToDict`` with the no-presence-fill flag (resolved by the
    KTD2 shim) and ``preserving_proto_field_name=True`` (snake_case keys), then
    prunes that dict to ``selection.paths``.

    The dense render already encodes R5/R6's presence-class rule: no-presence
    fields (implicit scalars, repeated, map, enums) are filled at their default;
    presence-bearing fields (proto3 ``optional``, ``oneof`` members, singular
    submessages) are present only when actually set. This holds *recursively* —
    a nested no-presence scalar fills while a nested presence-bearing field stays
    absent, inside submessage, ``map`` value, repeated-element, and ``oneof``
    submessage terminals. Pruning is a nested-key descent over a dict whose
    values are already materialized (so it reuses all of proto's leaf
    type-mapping — enums to names, int64 to string, bytes to base64), which makes
    the faithful view fall out for free:

    - A selected no-presence scalar at its default appears (it was filled).
    - A selected presence-bearing field that is unset is absent (the fill flag
      omitted it), so the path contributes nothing — no fabricated ``{}``.
    - A selected leaf under an unset submessage is absent (its ancestor key is
      missing from the dense dict, so the descent stops).

    Args:
        message: A parsed protobuf message (e.g. ``ScanRecord.message``).
        selection: A :class:`CompiledSelection` from :func:`compile_fields`,
            validated against ``message``'s descriptor.

    Returns:
        A new ``dict`` containing only the selected paths, preserving nesting and
        snake_case keys. ``map`` keys are preserved verbatim (they are data, not
        field names, so a camelCase map key is *not* re-cased). Terminal values
        are copied from the dense render by reference; the result is a faithful
        nested *view*, not required to be re-serializable.
    """
    dense = json_format.MessageToDict(
        message,
        preserving_proto_field_name=True,
        **{NO_PRESENCE_FILL_KWARG: True},
    )
    result: dict[str, Any] = {}
    for path in selection.paths:
        _graft(dense, result, path)
    return result


def _graft(
    dense: dict[str, Any], result: dict[str, Any], path: tuple[str, ...]
) -> None:
    """Copy ``dense``'s value at ``path`` into ``result`` at the same nesting.

    Descends ``dense`` by each non-terminal segment; if any segment is missing (a
    presence-bearing ancestor was unset, so the dense render omitted it), the
    path contributes nothing. Otherwise the terminal value is grafted into
    ``result`` at the nested path, creating intermediate dicts as needed. Every
    non-terminal segment is a singular submessage key (R2 forbids descent into
    repeated/map elements, enforced by ``compile_fields``), so each intermediate
    is a ``dict``.
    """
    src: dict[str, Any] = dense
    for seg in path[:-1]:
        if seg not in src:
            return  # presence-bearing ancestor unset -> nothing to graft
        src = src[seg]
    terminal = path[-1]
    if terminal not in src:
        return  # presence-bearing terminal unset
    dst = result
    for seg in path[:-1]:
        dst = dst.setdefault(seg, {})
    dst[terminal] = src[terminal]
