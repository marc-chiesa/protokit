"""Cross-cutting safety + acceptance suite (U7).

Integration-level tests that compose the full stack and prove the design's
load-bearing claims and the maintainer's three real questions at the granularity
each names. **No C-extension mocks** — every fault is driven with real bytes /
real descriptor sets.

- UAF / parse-confinement (D5/D11): the arena copy holds for scalar *and* bytes
  fields when the source's buffer is invalidated right after yield.
- Sequential multi-version (success criterion): conflicting same-FQN schemas in
  isolated pools, routed without cross-contamination.
- Assignment Q3 (corruption recovery), Q2 (cross-channel correlation), Q1
  (embedded-schema extraction), and beats-`protoc --decode`.
"""

from __future__ import annotations

import io
from collections.abc import Iterator

from google.protobuf import descriptor_pb2

from protokit.storage import (
    EmbeddedSchema,
    FileDescriptorSetSchema,
    StreamRegistry,
    scan,
)
from protokit.storage.sources import length_delimited
from tests.storage.proto_fixtures import delimited, encode_varint, fds, message_file

_INT32 = descriptor_pb2.FieldDescriptorProto.TYPE_INT32
_STRING = descriptor_pb2.FieldDescriptorProto.TYPE_STRING
_BYTES = descriptor_pb2.FieldDescriptorProto.TYPE_BYTES


class _BufferInvalidatingSource:
    """Yields a ``memoryview`` over a ``bytearray`` then zeroes it after yield."""

    def __init__(self, stream_id: str, payloads: list[bytes]) -> None:
        self._stream_id = stream_id
        self._payloads = payloads
        self.buffers: list[bytearray] = []

    def __iter__(self) -> Iterator[tuple[str, memoryview]]:
        for payload in self._payloads:
            buf = bytearray(payload)
            self.buffers.append(buf)
            yield (self._stream_id, memoryview(buf))
            for i in range(len(buf)):
                buf[i] = 0


class TestUseAfterFreeGuard:
    def test_arena_copy_holds_for_scalar_and_bytes_fields(self) -> None:
        # Headline D5 claim. A bytes field is the sharper test: upb returns a
        # COPY for bytes fields, so a zeroed source buffer must not corrupt it.
        fdp = message_file("a.proto", "a", "A", {"n": (_INT32, 1), "blob": (_BYTES, 2)})
        schema = FileDescriptorSetSchema(fds(fdp), "a.A")
        registry = StreamRegistry()
        registry.register_stream("s", schema)
        message_cls = schema.resolve().message_class
        payload = message_cls(n=7, blob=b"secret-bytes").SerializeToString()

        source = _BufferInvalidatingSource("s", [payload])
        records = list(scan(source, registry))

        # If the engine ever retained the live view, these would read as zeros.
        assert records[0].message.n == 7
        assert records[0].message.blob == b"secret-bytes"
        # Teeth: the backing buffer really was invalidated.
        assert set(source.buffers[0]) == {0}
        assert len(source.buffers[0]) > 0


class TestSequentialMultiVersion:
    def test_conflicting_same_fqn_schemas_route_without_contamination(self) -> None:
        # myapp.X means {int32 a} on one stream, {string label} on another.
        v1 = message_file("u.proto", "myapp", "X", {"a": (_INT32, 1)})
        v2 = message_file("u.proto", "myapp", "X", {"label": (_STRING, 1)})
        registry = StreamRegistry()
        registry.register_stream("v1", FileDescriptorSetSchema(fds(v1), "myapp.X"))
        registry.register_stream("v2", FileDescriptorSetSchema(fds(v2), "myapp.X"))
        c1 = FileDescriptorSetSchema(fds(v1), "myapp.X").resolve().message_class
        c2 = FileDescriptorSetSchema(fds(v2), "myapp.X").resolve().message_class

        feed = [
            ("v1", c1(a=11).SerializeToString()),
            ("v2", c2(label="ship").SerializeToString()),
            ("v1", c1(a=22).SerializeToString()),
        ]
        records = list(scan(iter(feed), registry))

        assert [r.stream_id for r in records] == ["v1", "v2", "v1"]
        assert records[0].message.a == 11
        assert records[1].message.label == "ship"
        assert records[2].message.a == 22
        # No cross-contamination: each message carries only its own fields.
        assert {f.name for f in records[0].message.DESCRIPTOR.fields} == {"a"}
        assert {f.name for f in records[1].message.DESCRIPTOR.fields} == {"label"}


class TestAssignmentQ3CorruptionRecovery:
    def test_collect_returns_all_good_and_reports_each_bad_record(self) -> None:
        fdp = message_file("a.proto", "a", "A", {"n": (_INT32, 1)})
        schema = FileDescriptorSetSchema(fds(fdp), "a.A")
        registry = StreamRegistry()
        registry.register_stream("s", schema)
        message_cls = schema.resolve().message_class
        good1 = message_cls(n=1).SerializeToString()
        good2 = message_cls(n=2).SerializeToString()

        # good1 | undecodable frame body b"\x08" | good2 | truncated trailing frame
        stream_bytes = (
            delimited(good1, b"\x08", good2)
            + encode_varint(9)  # declare a 9-byte body...
            + b"\x08\x08"  # ...but supply only 2 -> truncation
        )
        source = length_delimited(io.BytesIO(stream_bytes), stream_id="s")
        result = scan(source, registry, on_error="collect")
        records = list(result)

        assert [r.message.n for r in records] == [1, 2]  # every well-formed record
        errors = result.errors
        assert len(errors) == 2
        # Engine decode failure at the undecodable frame (record_index 1).
        assert errors[0].record_index == 1
        # Source-framing truncation at the trailing frame (record_index 3), with
        # a byte offset — exactly the report Q3 asks for.
        assert errors[1].record_index == 3
        assert errors[1].offset is not None
        assert all(e.stream_id == "s" for e in errors)


class TestAssignmentQ2CrossChannelCorrelation:
    def test_stream_id_on_output_enables_cross_channel_join(self) -> None:
        orders = message_file(
            "o.proto", "shop", "Order", {"order_id": (_INT32, 1), "total": (_INT32, 2)}
        )
        shipments = message_file(
            "s.proto", "shop", "Shipment",
            {"order_id": (_INT32, 1), "carrier": (_STRING, 2)},
        )
        registry = StreamRegistry()
        registry.register_stream("orders", FileDescriptorSetSchema(fds(orders), "shop.Order"))
        registry.register_stream(
            "shipments", FileDescriptorSetSchema(fds(shipments), "shop.Shipment")
        )
        order_cls = FileDescriptorSetSchema(fds(orders), "shop.Order").resolve().message_class
        shipment_cls = (
            FileDescriptorSetSchema(fds(shipments), "shop.Shipment").resolve().message_class
        )

        feed = [
            ("orders", order_cls(order_id=1, total=100).SerializeToString()),
            ("shipments", shipment_cls(order_id=1, carrier="ups").SerializeToString()),
            ("orders", order_cls(order_id=2, total=200).SerializeToString()),
            ("shipments", shipment_cls(order_id=2, carrier="fedex").SerializeToString()),
        ]
        # Correlate across channels by stream_id + the shared order_id key
        # (never by record_index).
        by_order: dict[int, dict[str, object]] = {}
        for record in scan(iter(feed), registry):
            by_order.setdefault(record.message.order_id, {})[record.stream_id] = record.message

        assert by_order[1]["orders"].total == 100  # type: ignore[attr-defined]
        assert by_order[1]["shipments"].carrier == "ups"  # type: ignore[attr-defined]
        assert by_order[2]["orders"].total == 200  # type: ignore[attr-defined]
        assert by_order[2]["shipments"].carrier == "fedex"  # type: ignore[attr-defined]


class TestAssignmentQ1EmbeddedSchemaExtraction:
    def test_embedded_channel_schema_is_recoverable_for_compat(self) -> None:
        orders = message_file(
            "o.proto", "shop", "Order", {"order_id": (_INT32, 1), "total": (_INT32, 2)}
        )
        channel = (fds(orders).SerializeToString(), "shop.Order")
        resolved = EmbeddedSchema(channel).resolve()

        # The channel's schema is recoverable: the resolved descriptor matches
        # the declared type, so a downstream `protokit compat` check could run
        # against it. (The compatibility VERDICT is the protokit.schema pillar;
        # data-conformance drift + migration is Phase 2.)
        descriptor = resolved.pool.FindMessageTypeByName("shop.Order")
        assert descriptor.full_name == "shop.Order"
        assert {f.name for f in descriptor.fields} == {"order_id", "total"}
        assert resolved.message_class(order_id=5, total=50).order_id == 5


class TestBeatsProtocDecode:
    def test_scan_filter_materialize_in_one_call(self) -> None:
        fdp = message_file("a.proto", "a", "A", {"n": (_INT32, 1)})
        schema = FileDescriptorSetSchema(fds(fdp), "a.A")
        registry = StreamRegistry()
        registry.register_stream("s", schema)
        message_cls = schema.resolve().message_class
        payloads = [message_cls(n=i).SerializeToString() for i in range(10)]

        source = length_delimited(io.BytesIO(delimited(*payloads)), stream_id="s")
        # One call scans a multi-record stream, filters, and materializes — the
        # capability `protoc --decode` (one message at a time, text-only) lacks.
        matched = [r.message.n for r in scan(source, registry, predicate=lambda m: m.n >= 7)]
        assert matched == [7, 8, 9]
