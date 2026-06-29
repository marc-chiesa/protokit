"""Schema-less wire-format field walker.

Decodes the top-level ``(field_number, wire_type)`` observations from raw,
untrusted protobuf bytes without any descriptor — the foundation for ``drift``
(per-field reconciliation against a candidate schema) and for the Phase-B
tie-break in ``match``.

Robustness is load-bearing because the input is untrusted: a varint is rejected
past 10 bytes / 64 bits, and a length-delimited prefix is bounds-checked against
the remaining buffer *before* any slice. The walk is top-level only — it does not
recurse into wire-type-2 submessages (also the deep-nesting DoS mitigation) — and
a group field (legacy wire types 3/4) is *flagged* at the top level and its body
skipped iteratively (no recursion), never deep-parsed.
"""

from __future__ import annotations

from typing import NamedTuple

from protokit.forensics._errors import ForensicsError

WIRETYPE_VARINT = 0
WIRETYPE_FIXED64 = 1
WIRETYPE_LEN = 2
WIRETYPE_SGROUP = 3
WIRETYPE_EGROUP = 4
WIRETYPE_FIXED32 = 5

_MAX_VARINT_BYTES = 10
_VARINT_FINAL_BYTE_MAX = 0x01


class WalkError(ForensicsError):
    """The raw bytes are not well-formed protobuf wire format (truncated / malformed)."""


class WireObservation(NamedTuple):
    """One top-level field observed on the wire, schema-free."""

    field_number: int
    wire_type: int


def _read_varint(data: bytes, pos: int) -> tuple[int, int]:
    """Read one base-128 varint at ``pos``; return ``(value, new_pos)``.

    Rejects a varint that runs off the end of the buffer or overflows 64 bits —
    an untrusted tag or length prefix must never yield a nonsense huge number or
    loop unbounded.
    """
    result = 0
    shift = 0
    consumed = 0
    n = len(data)
    while True:
        if pos >= n:
            raise WalkError("truncated varint: stream ended mid-value")
        byte = data[pos]
        pos += 1
        consumed += 1
        if consumed > _MAX_VARINT_BYTES or (
            consumed == _MAX_VARINT_BYTES and byte & 0x7F > _VARINT_FINAL_BYTE_MAX
        ):
            raise WalkError("varint exceeds 64 bits (malformed)")
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, pos
        shift += 7


def _skip_scalar_payload(data: bytes, pos: int, wire_type: int) -> int:
    """Advance past a non-group field's payload; raise on truncation / bad wire type."""
    n = len(data)
    if wire_type == WIRETYPE_VARINT:
        _, pos = _read_varint(data, pos)
        return pos
    if wire_type == WIRETYPE_FIXED64:
        if pos + 8 > n:
            raise WalkError("truncated fixed64 field")
        return pos + 8
    if wire_type == WIRETYPE_FIXED32:
        if pos + 4 > n:
            raise WalkError("truncated fixed32 field")
        return pos + 4
    if wire_type == WIRETYPE_LEN:
        length, pos = _read_varint(data, pos)
        if length < 0 or pos + length > n:
            raise WalkError(
                "length-delimited prefix exceeds the remaining buffer "
                f"(declared {length}, available {n - pos})"
            )
        return pos + length
    raise WalkError(f"invalid wire type {wire_type}")


def walk_top_level(data: bytes) -> list[WireObservation]:
    """Observe the top-level ``(field_number, wire_type)`` fields in ``data``.

    Group fields are recorded once at the top level (wire type 3) and their body
    is skipped iteratively to the matching end-group; nested fields inside a group
    are not recorded. Raises :class:`WalkError` on any truncation, an unknown wire
    type, field number 0, or an unbalanced group.
    """
    observations: list[WireObservation] = []
    pos = 0
    depth = 0
    n = len(data)
    while pos < n:
        tag, pos = _read_varint(data, pos)
        field_number = tag >> 3
        wire_type = tag & 0x07
        if field_number == 0:
            raise WalkError("field number 0 is invalid")
        if wire_type == WIRETYPE_EGROUP:
            if depth == 0:
                raise WalkError("unexpected end-group at the top level")
            depth -= 1
            continue
        if depth == 0:
            observations.append(WireObservation(field_number, wire_type))
        if wire_type == WIRETYPE_SGROUP:
            depth += 1
            continue
        pos = _skip_scalar_payload(data, pos, wire_type)
    if depth != 0:
        raise WalkError("unterminated group (no matching end-group)")
    return observations
