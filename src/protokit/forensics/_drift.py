"""Per-field drift: reconcile observed wire data against one candidate schema.

``drift`` walks a message's top-level ``(field_number, wire_type)`` observations
(schema-free, via :mod:`protokit.forensics._wire`) and classifies each against a
chosen candidate descriptor: an undeclared tag, a wire-type mismatch on a
declared field, a reserved tag in use, or (proto2) a declared ``required`` field
absent from the message. A tag that is a declared proto2 *extension* counts as
declared (not undeclared). The same reconciliation feeds the Phase-B match
tie-break via :func:`compatibility_score`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from google.protobuf import descriptor_pb2
from google.protobuf.descriptor import Descriptor, FieldDescriptor

from protokit.forensics._wire import WIRETYPE_LEN, WireObservation, walk_top_level
from protokit.storage.schema_source import ResolvedSchema, SchemaSource

# Expected wire type for each FieldDescriptor.type.
_WIRE_TYPE_BY_FIELD_TYPE: dict[int, int] = {
    FieldDescriptor.TYPE_DOUBLE: 1,
    FieldDescriptor.TYPE_FIXED64: 1,
    FieldDescriptor.TYPE_SFIXED64: 1,
    FieldDescriptor.TYPE_FLOAT: 5,
    FieldDescriptor.TYPE_FIXED32: 5,
    FieldDescriptor.TYPE_SFIXED32: 5,
    FieldDescriptor.TYPE_INT64: 0,
    FieldDescriptor.TYPE_UINT64: 0,
    FieldDescriptor.TYPE_INT32: 0,
    FieldDescriptor.TYPE_UINT32: 0,
    FieldDescriptor.TYPE_SINT32: 0,
    FieldDescriptor.TYPE_SINT64: 0,
    FieldDescriptor.TYPE_BOOL: 0,
    FieldDescriptor.TYPE_ENUM: 0,
    FieldDescriptor.TYPE_STRING: 2,
    FieldDescriptor.TYPE_BYTES: 2,
    FieldDescriptor.TYPE_MESSAGE: 2,
    FieldDescriptor.TYPE_GROUP: 3,
}
#: Scalar wire types a packable ``repeated`` field may carry packed (as wire-type 2).
_PACKABLE_WIRE_TYPES = frozenset({0, 1, 5})

DivergenceKind = Literal[
    "undeclared", "wire_type_mismatch", "reserved_in_use", "required_missing"
]


@dataclass(frozen=True)
class FieldDivergence:
    """One way the observed wire data diverges from the chosen candidate schema."""

    field_number: int
    kind: DivergenceKind
    detail: str


@dataclass(frozen=True)
class DriftReport:
    """The per-field divergences of a message against one candidate schema."""

    divergences: tuple[FieldDivergence, ...]
    observed_field_count: int


def _declared_numbers(
    descriptor: Descriptor,
) -> tuple[dict[int, FieldDescriptor], dict[int, FieldDescriptor]]:
    """Return ``(regular_fields, declared_extensions)`` keyed by field number."""
    regular: dict[int, FieldDescriptor] = {fd.number: fd for fd in descriptor.fields}
    extensions: dict[int, FieldDescriptor] = {
        ext.number: ext for ext in descriptor.file.pool.FindAllExtensions(descriptor)
    }
    return regular, extensions


def _reserved_numbers(descriptor: Descriptor) -> set[int]:
    """Field numbers the descriptor reserves (read via ``CopyToProto``)."""
    proto = descriptor_pb2.DescriptorProto()
    descriptor.CopyToProto(proto)
    reserved: set[int] = set()
    for rng in proto.reserved_range:
        reserved.update(range(rng.start, rng.end))  # end is exclusive
    return reserved


def _wire_type_ok(field: FieldDescriptor, observed: int) -> bool:
    """Whether ``observed`` wire type is compatible with ``field``'s declared type.

    A packable ``repeated`` scalar field accepts both its element wire type and
    the packed length-delimited encoding (wire type 2).
    """
    expected = _WIRE_TYPE_BY_FIELD_TYPE.get(field.type)
    if expected is None:
        return True  # unknown field type — do not flag a mismatch
    if field.label == FieldDescriptor.LABEL_REPEATED and expected in _PACKABLE_WIRE_TYPES:
        return observed in (expected, WIRETYPE_LEN)
    return observed == expected


def _classify(
    observations: list[WireObservation], descriptor: Descriptor
) -> list[FieldDivergence]:
    """Classify each observation against ``descriptor`` and add required-missing."""
    regular, extensions = _declared_numbers(descriptor)
    reserved = _reserved_numbers(descriptor)
    divergences: list[FieldDivergence] = []
    observed_numbers: set[int] = set()

    for obs in observations:
        observed_numbers.add(obs.field_number)
        if obs.field_number in reserved:
            divergences.append(
                FieldDivergence(
                    obs.field_number,
                    "reserved_in_use",
                    f"field {obs.field_number} is reserved by the schema",
                )
            )
            continue
        field = regular.get(obs.field_number) or extensions.get(obs.field_number)
        if field is None:
            divergences.append(
                FieldDivergence(
                    obs.field_number,
                    "undeclared",
                    f"field {obs.field_number} (wire type {obs.wire_type}) is not declared",
                )
            )
            continue
        if not _wire_type_ok(field, obs.wire_type):
            expected = _WIRE_TYPE_BY_FIELD_TYPE.get(field.type)
            divergences.append(
                FieldDivergence(
                    obs.field_number,
                    "wire_type_mismatch",
                    f"field {obs.field_number}: observed wire type {obs.wire_type}, "
                    f"schema declares wire type {expected}",
                )
            )

    for field in descriptor.fields:
        if (
            field.label == FieldDescriptor.LABEL_REQUIRED
            and field.number not in observed_numbers
        ):
            divergences.append(
                FieldDivergence(
                    field.number,
                    "required_missing",
                    f"required field '{field.name}' (#{field.number}) is absent",
                )
            )
    return divergences


def drift(message_bytes: bytes, source: SchemaSource) -> DriftReport:
    """Reconcile ``message_bytes`` against one candidate schema, field by field."""
    resolved: ResolvedSchema = source.resolve()
    descriptor: Descriptor = resolved.message_class.DESCRIPTOR
    observations = walk_top_level(message_bytes)
    return DriftReport(tuple(_classify(observations, descriptor)), len(observations))


def compatibility_score(
    observations: list[WireObservation], descriptor: Descriptor
) -> int:
    """Net per-field compatibility: declared-and-wire-type-agreeing minus the rest.

    Higher is a tighter wire-level fit. Used by the Phase-B ``match`` tie-break to
    separate candidates whose scalar modeled-byte fractions are near-identical.
    """
    regular, extensions = _declared_numbers(descriptor)
    reserved = _reserved_numbers(descriptor)
    score = 0
    for obs in observations:
        if obs.field_number in reserved:
            score -= 1
            continue
        field = regular.get(obs.field_number) or extensions.get(obs.field_number)
        if field is None:
            score -= 1
        elif _wire_type_ok(field, obs.wire_type):
            score += 1
        else:
            score -= 1
    return score
