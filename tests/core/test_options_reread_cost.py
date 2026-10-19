"""Reading options back from a schema's file costs time in proportion to the file.

Once the default pool declares an extension an options message could hold,
``protokit._extensions.options_of`` reads each descriptor's options from the
file it was built from, and finds the descriptor's declaration there. A message
or an enum carries no index, so it is found by name in its scope. Scanning that
scope for every field made a read of a whole schema quadratic: a file of 2000
messages of ten fields took ``check_compatibility`` 7.5 s under upb, against
0.1 s while the default pool declared nothing.

Counting is the measure here, not the clock: the file read hands out a copy
whose declarations count each one handed out, and every descriptor's options
are read once. A read that visits each declaration a bounded number of times
passes whatever the machine; one that scans a scope per lookup visits the top
level once per descriptor and fails by a wide margin.

The default pool is never touched: like ``test_extensions_default_pool``'s
in-process tests, these only pretend it declares something.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from google.protobuf import descriptor_pb2

from protokit import _extensions
from protokit._extensions import options_of
from protokit._pools import build_pool

FD = descriptor_pb2.FieldDescriptorProto
_PKG = "pkreread"
_MESSAGES = 60
_FIELDS = 10

# Every attribute of a declaration that holds more declarations.
_DECLARATIONS = frozenset({
    "message_type", "nested_type", "enum_type", "field", "extension", "value",
    "service", "method", "oneof_decl",
})


class _Visits:
    count = 0


class _Counted:
    """A declaration whose declarations count each one they hand out."""

    def __init__(self, proto: Any, visits: _Visits) -> None:
        self._proto = proto
        self._visits = visits

    def __getattr__(self, name: str) -> Any:
        value = getattr(self._proto, name)
        if name in _DECLARATIONS:
            return _CountedList(value, self._visits)
        return value


class _CountedList:
    def __init__(self, items: Any, visits: _Visits) -> None:
        self._items = items
        self._visits = visits

    def __len__(self) -> int:
        return len(self._items)

    def __getitem__(self, index: int) -> _Counted:
        self._visits.count += 1
        return _Counted(self._items[index], self._visits)

    def __iter__(self) -> Iterator[_Counted]:
        for item in self._items:
            self._visits.count += 1
            yield _Counted(item, self._visits)


def _schema(package: str) -> descriptor_pb2.FileDescriptorSet:
    """``_MESSAGES`` records, each holding fields, a nested message and a nested enum."""
    f = descriptor_pb2.FileDescriptorProto(
        name=f"{package}.proto", package=package, syntax="proto3",
    )
    for i in range(_MESSAGES):
        record = f.message_type.add(name=f"Record{i}")
        for j in range(_FIELDS):
            record.field.add(
                name=f"s{j}", number=j + 1, type=FD.TYPE_STRING, label=FD.LABEL_OPTIONAL,
            )
        detail = record.nested_type.add(name="Detail")
        detail.field.add(name="note", number=1, type=FD.TYPE_STRING, label=FD.LABEL_OPTIONAL)
        kind = record.enum_type.add(name="Kind")
        kind.value.add(name=f"KIND_{i}_UNSPECIFIED", number=0)
        kind.value.add(name=f"KIND_{i}_SOME", number=1)
    root = f.message_type.add(name="Root")
    for i in range(_MESSAGES):
        root.field.add(
            name=f"r{i}", number=i + 1, type=FD.TYPE_MESSAGE, label=FD.LABEL_OPTIONAL,
            type_name=f".{package}.Record{i}",
        )
    return descriptor_pb2.FileDescriptorSet(file=[f])


def _descriptors(message: Any) -> Iterator[Any]:
    """``message`` and every descriptor declared inside it, at any depth."""
    yield message
    yield from message.fields
    for enum in message.enum_types:
        yield enum
        yield from enum.values
    for nested in message.nested_types:
        yield from _descriptors(nested)


class TestReadingEveryOptionFromTheFile:
    def test_visits_each_declaration_a_bounded_number_of_times(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # A package of its own, so no cache already holds this file.
        package = f"{_PKG}_bounded"
        pool = build_pool(_schema(package))
        file_desc = pool.FindFileByName(f"{package}.proto")
        descriptors = [
            desc
            for message in file_desc.message_types_by_name.values()
            for desc in _descriptors(message)
        ]
        file_proto = _extensions._file_proto(file_desc)
        visits = _Visits()
        monkeypatch.setattr(_extensions, "_default_pool_extends", lambda options_type: True)
        monkeypatch.setattr(
            _extensions, "_file_proto", lambda fd: _Counted(file_proto, visits),
        )

        read = [options_of(desc) for desc in descriptors]

        # Every descriptor was read from the file, and read right.
        assert all(type(options) is not type(desc.GetOptions()) for options, desc in zip(
            read, descriptors, strict=True,
        ))
        assert [options.SerializeToString() for options in read] == [
            desc.GetOptions().SerializeToString() for desc in descriptors
        ]
        # Each declaration is visited a bounded number of times. Scanning the
        # top level per lookup visits it once for every descriptor read: about
        # (_MESSAGES + 1) * len(descriptors) visits, 50 times this bound.
        assert visits.count <= 3 * len(descriptors), (
            f"{visits.count} visits to read {len(descriptors)} descriptors"
        )


class TestAMessageInsideOneDeclaredTwice:
    """Pure-Python builds a file declaring one message name twice; upb refuses it.

    The index files both twins' nested declarations under one path. A lookup
    must still find the enclosing message first and give way to
    ``GetOptions()`` there, as a scan of each scope did, not answer from the
    nested declaration that happens to be the only one of its name.
    """

    @staticmethod
    def _file() -> descriptor_pb2.FileDescriptorProto:
        f = descriptor_pb2.FileDescriptorProto(name=f"{_PKG}_twins.proto", syntax="proto2")
        first = f.message_type.add(name="Twin")
        first.nested_type.add(name="Only").field.add(
            name="f", number=1, type=FD.TYPE_INT32, label=FD.LABEL_OPTIONAL,
        ).options.deprecated = True
        first.nested_type[0].options.deprecated = True
        first.nested_type[0].enum_type.add(name="Shade").value.add(name="DARK", number=0)
        f.message_type.add(name="Twin").nested_type.add(name="Other")
        return f

    def test_the_file_read_gives_way_to_get_options(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from google.protobuf import descriptor_pool
        from google.protobuf.internal import api_implementation

        monkeypatch.setattr(_extensions, "_default_pool_extends", lambda options_type: True)
        pool = descriptor_pool.DescriptorPool()
        if api_implementation.Type() != "python":
            with pytest.raises(TypeError, match="duplicate symbol"):
                pool.AddSerializedFile(self._file().SerializeToString())
            return
        pool.AddSerializedFile(self._file().SerializeToString())
        only = pool.FindMessageTypeByName("Twin.Only")
        shade = only.enum_types_by_name["Shade"]
        for desc in (only, only.fields[0], shade, shade.values[0]):
            assert options_of(desc) is desc.GetOptions()
