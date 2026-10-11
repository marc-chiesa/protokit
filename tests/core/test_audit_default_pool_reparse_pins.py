"""Strict-xfail pins: a schema's file is still parsed through the default pool.

Found 2026-10-11, after the 0.16.0 re-audit, while fixing what ``GetOptions()``
does under upb (``protokit._extensions.options_of``). No audit finding ID and
no release owns it yet.

protokit reads a schema's files through ``descriptor_pb2`` classes: the
loaders parse a ``FileDescriptorSet`` with one, and ``CopyToProto`` and
``FileDescriptorProto.FromString(file.serialized_pb)`` fill one. Those classes
decode an option through the extensions the *default* pool declares for its
number, on both backends. So once the process has registered an unrelated
extension that uses one of the schema's option numbers for another type:

- a set loaded afterwards is refused as unparseable where the option's bytes
  do not decode as that type, and loaded with the value rewritten where they
  do (an ``int32`` ``7`` under a ``bool`` is stored, and read, as ``1``);
- a schema loaded *before* that still cannot be copied back to a proto, so
  ``check_compatibility`` raises ``DecodeError`` before any rule runs.

The same re-parse happens in ``protokit._descriptors._file_message_index``,
``protokit._fieldview`` (two syntax lookups), the lint engine's import graph
and the lint rules in ``rules/file.py``, ``rules/imports.py`` and
``rules/field.py``; only the two loaders and ``check_compatibility`` are
measured here.

Registering an extension in the default pool cannot be undone, so every
scenario runs in a fresh interpreter. Each pin asserts the outcome a correct
implementation produces and is narrowed to ``AssertionError``: a scenario that
does not run raises ``RuntimeError`` and turns the pin red.
"""

from __future__ import annotations

import functools
import json
import os
import subprocess
import sys
import tempfile
from typing import Any

import pytest

from tests.core.test_extensions_default_pool import (
    _SRC,
    COMPAT_DOES_NOT_COMPLETE,
    compat_outcome,
)

# argv: scenario name, scratch directory. Prints one JSON object.
_LOADED_AFTERWARDS = r"""
import json
import sys
from pathlib import Path

from google.protobuf import descriptor_pb2 as d, descriptor_pool as dp

from protokit._pools import DescriptorPoolError, load_pool_from_bytes
from protokit.options import get_option_value
from protokit.schema.lint._cli_utils import _load_descriptor_sets_to_result

FD = d.FieldDescriptorProto
scenario, scratch = sys.argv[1], Path(sys.argv[2])


def varint(n):
    out = bytearray()
    while n > 0x7F:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    out.append(n)
    return bytes(out)


def record(number, wire_type, payload):
    body = varint(len(payload)) + payload if wire_type == 2 else payload
    return varint(number << 3 | wire_type) + body


def options_file(name, package, extensions):
    f = d.FileDescriptorProto(
        name=name, package=package, syntax="proto2",
        dependency=["google/protobuf/descriptor.proto"],
    )
    f.message_type.add(name="Info").field.add(
        name="s", number=1, type=FD.TYPE_STRING, label=FD.LABEL_OPTIONAL,
    )
    for ext_name, number, kind, type_name in extensions:
        ext = f.extension.add(
            name=ext_name, number=number, type=kind, label=FD.LABEL_OPTIONAL,
            extendee=".google.protobuf.FieldOptions",
        )
        if type_name:
            ext.type_name = type_name
    return f


# Every byte well formed: label = "hello world", count = 7.
mine = options_file("mine/opts.proto", "mine", [
    ("label", 70001, FD.TYPE_STRING, None), ("count", 70003, FD.TYPE_INT32, None),
])
target = d.FileDescriptorProto(
    name="mine/t.proto", package="mine", syntax="proto3", dependency=["mine/opts.proto"],
)
target.message_type.add(name="M").field.add(
    name="f", number=1, type=FD.TYPE_INT32, label=FD.LABEL_OPTIONAL,
).options.MergeFromString(record(70001, 2, b"hello world") + record(70003, 0, varint(7)))
fds = d.FileDescriptorSet()
d.DESCRIPTOR.CopyToProto(fds.file.add())
fds.file.extend([mine, target])
data = fds.SerializeToString()
path = scratch / "set.binpb"
path.write_bytes(data)

theirs = {
    "nothing": [],
    "another-type-at-the-number": [("meta", 70001, FD.TYPE_MESSAGE, ".theirs.Info")],
    "another-scalar-at-the-number": [("flag", 70003, FD.TYPE_BOOL, None)],
}[scenario]
if theirs:
    dp.Default().AddSerializedFile(
        options_file("theirs/opts.proto", "theirs", theirs).SerializeToString()
    )


def read(pool):
    f = pool.FindMessageTypeByName("mine.M").fields_by_name["f"]
    return [get_option_value(f, "mine.label"), get_option_value(f, "mine.count")]


def pool_loader():
    try:
        return read(load_pool_from_bytes(data))
    except DescriptorPoolError:
        return "DescriptorPoolError"


def lint_loader():
    try:
        return read(_load_descriptor_sets_to_result((path,)).pool)
    except SystemExit as exc:
        return f"exit {exc.code}"


print(json.dumps({"pool_loader": pool_loader(), "lint_loader": lint_loader()}))
"""

_LOADERS = ("pool_loader", "lint_loader")
_UNOWNED = (
    "Unowned (found 2026-10-11, after the 0.16.0 re-audit; no release assigned). "
    "A schema's files are parsed through descriptor_pb2 classes, which decode an "
    "option through whatever the default pool declares for its number. "
)


@functools.cache
def _loaded_afterwards(scenario: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as scratch:
        result = subprocess.run(
            [sys.executable, "-c", _LOADED_AFTERWARDS, scenario, scratch],
            capture_output=True, text=True, check=False, timeout=300,
            env={**os.environ, "PYTHONPATH": str(_SRC)},
        )
    if result.returncode != 0:
        # Not an assertion: a pin that expects AssertionError must not accept this.
        raise RuntimeError(f"scenario {scenario!r} did not run:\n{result.stderr}")
    outcome: dict[str, Any] = json.loads(result.stdout.strip().splitlines()[-1])
    return outcome


@pytest.mark.parametrize("loader", _LOADERS)
def test_the_set_loads_and_reads_while_the_default_pool_declares_nothing(loader: str) -> None:
    """The control: each pin below fails for the registration it names, not the fixture."""
    assert _loaded_afterwards("nothing")[loader] == ["hello world", 7]


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=_UNOWNED + (
        "An unrelated message-typed extension at a string option's number makes the "
        "loader refuse the whole set: DescriptorPoolError from load_pool_from_bytes, "
        "error[lint-bad-input] and exit 2 from the lint loader. Both backends."
    ),
)
@pytest.mark.parametrize("loader", _LOADERS)
def test_a_well_formed_set_loads_whatever_the_default_pool_declares(loader: str) -> None:
    assert _loaded_afterwards("another-type-at-the-number")[loader] == ["hello world", 7]


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=_UNOWNED + (
        "An unrelated bool extension at an int32 option's number makes the loader "
        "store the value as the bool encodes it: 7 is loaded, and read, as 1. Both "
        "backends, and nothing is reported."
    ),
)
@pytest.mark.parametrize("loader", _LOADERS)
def test_a_loaded_option_keeps_the_value_its_file_holds(loader: str) -> None:
    assert _loaded_afterwards("another-scalar-at-the-number")[loader] == ["hello world", 7]


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=_UNOWNED + (
        "check_compatibility copies each file back to a FileDescriptorProto "
        "(_descriptors._file_message_index), and where the default pool's type cannot "
        "decode an option's bytes that copy raises DecodeError before any rule runs, "
        "on a schema loaded before the registration. Both backends."
    ),
)
@pytest.mark.parametrize(("scenario", "later"), COMPAT_DOES_NOT_COMPLETE)
def test_check_compatibility_completes_whatever_the_default_pool_declares(
    scenario: str, later: str
) -> None:
    got, expected = compat_outcome(scenario, later)
    assert got == expected
