"""Regression pins for deferred cycle-2 audit findings on field names (family C, field names).

Every ``xfail`` in this module pins a LIVE defect that a later release owns.
Each pin is ``@pytest.mark.xfail(strict=True, raises=...)`` on the test
function itself, with a ``reason`` that begins with the finding ID and names
the owning unit and release. The suite stays green while the defect exists and
the pin flips to a hard failure (XPASS under strict mode) the day the mechanism
is fixed, so a fix cannot land silently and no pin can rot into a
permanently-red test.

Each pin asserts the correct outcome, and ``raises=`` names the exception that
was observed with ``--runxfail --tb=line`` under both protobuf backends, so a
pin that dies anywhere else is red rather than "expected". A passing control
sits beside every pin and shares its construction, with the one field (or
nested type) renamed to a name no generated class uses: a red control says the
harness broke, a red pin says the defect moved.

The family. A generated message class carries methods and attributes
(``ListFields``, ``MergeFromString``, ``DESCRIPTOR``, ``Extensions``,
``_Modified``, ...), and a schema may declare a field or a nested type of the
same name. Under upb the field (or the nested class) hides the attribute on the
instance; under pure-Python the attribute hides the field. One seam reads past
both, ``protokit._fieldview._unshadowed`` (and ``_extensions_of`` for the
``Extensions`` mapping), and the call sites below do not go through it. Which
backend fails depends on the site, so most pins here hold on one backend only.
Where the runtime can serve the schema the correct outcome is the ordinary
answer. Where it cannot (pure-Python cannot build a class with a field named
``DESCRIPTOR``, and ``json_format`` cannot set a field named ``Clear``), the
fixed outcome is not settled: the call works, or protokit refuses with a typed
error (a CLI exit 2), and the pin fails only on the raw exception. A CLI pin
that accepts exit 2 accepts it only as a refusal of this input: a usage error,
or an exit 2 whose message names neither the field, the type nor (for ``diff``)
the file it would not parse, is red.

**Pins that hold on one backend only** use a conditional marker, still on the
test function and still strict: ``condition=_PURE_PYTHON_BACKEND`` for a
defect only the pure-Python runtime shows, and ``condition=_UPB_BACKEND`` for
one only upb shows. On the other backend the marker does not apply and the
test runs as an ordinary passing test, which makes it that backend's control
for the pin. A pin whose other backend fails for a different, separately
pinned reason is skipped there instead (C14-C3 under pure-Python, which cannot
build the class at all: C02-C3 below).

Pinned here (every pin is owned by U17a, 0.19.0, its final guard-widening
step):

* **C01-C5** (= C01-X2) — pure-Python only. ``get_option_value`` beside a
  repeated message-typed option whose element type has a field named
  ``DESCRIPTOR``: the first read of any option on that descriptor raises
  ``AttributeError`` while the option bytes are parsed (building the element's
  class fails); a second read returns the value. Each test builds its own pool.
* **C02-C3**, the ``DESCRIPTOR`` half — pure-Python only. ``get_message_class``
  on a type with a field named ``DESCRIPTOR`` raises a raw ``AttributeError``,
  so ``storage count``, ``forensics drift`` and ``forensics match`` end in a
  traceback. The ``storage count`` parameter is also C09-C4's route (the
  storage schema classes), which has no pin of its own. The finding's
  ``RecursionError`` half has another owner and is pinned elsewhere.
* **C02-C7** — both backends. ``get_option_value`` walks a sub-path below a
  set message option with ``getattr``, so a segment that names no field but
  names a method (``cfg.ByteSize``) returns the bound method, not ``None``.
* **C02-X1** — pure-Python only. The same walk, on a sub-field that IS named
  ``ByteSize`` or ``SerializeToString``: the method wins and the walk returns
  it instead of the field's value.
* **C10-C1b** — pure-Python only. ``protokit diff --json`` on a type with a
  field named ``Clear``: ``json_format`` cannot set the field and raises a raw
  ``AttributeError``.
* **C10-C5** — both backends. ``protokit diff`` (binary input) on a type with a
  field named ``ParseFromString``: ``msg.ParseFromString`` is the field's
  value, and calling it raises ``TypeError``.
* **C14-C1** (= C14-X1) — upb only. ``scan`` parses each record with
  ``message.MergeFromString``, which on a type with a field of that name is the
  field's value: the ``TypeError`` escapes every ``on_error`` mode.
* **C17-C6** — ``forensics.match`` on a candidate with a field named
  ``MergeFromString``, ``ListFields``, ``ByteSize`` or ``DiscardUnknownFields``
  aborts the ranking with ``TypeError`` under upb; ``CopyFrom`` does under both
  backends (its own pin). ``IsInitialized`` is fixed (C17-C6b) and is not
  pinned.
* **C14-C3** — upb only, and only where ``ptars`` and ``pyarrow`` import.
  ``to_parquet`` and ``to_arrow_batches`` check ``message.DESCRIPTOR``, which
  on a type with a field named ``DESCRIPTOR`` is the field's value.
* **C04-X5**, what the 0.16.0 fix left — two pins. Pure-Python: two identical
  messages with a field named ``ListFields`` are reported ``MODIFIED`` (the
  differ reads the bound method, twice). upb: a message with that field set on
  one side only raises ``TypeError`` on the one-sided route
  (``_has_populated_fields`` and ``_emit_all_fields`` both call it).

Five members with no finding ID, found while the family was pinned, same owner:

* pure-Python: ``compare`` on a type with an extension range and a field named
  ``Extensions`` reads the extension mapping instead of the field and raises
  ``AttributeError``, unless that field is ignored.
* pure-Python: ``compare`` on a type with a message field named ``_Modified``
  or ``__str__`` reads the method and raises ``AttributeError`` at the next
  level.
* upb: ``protokit diff --text-format`` / ``--json`` on input that sets an
  extension, on a type with a field named ``Extensions`` (``AttributeError``)
  or ``HasExtension`` (``--text-format``, ``TypeError``): protobuf's own parser
  reads the field's value as the member and the exception ends the run.
* upb: a generated-style class (nested classes in the class dictionary, as a
  ``_pb2`` module builds them) with a nested message type named ``HasField``:
  ``compare`` calls the nested class in ``field_present``'s declared-field
  branch and raises ``TypeError``.
* pure-Python: ``storage scan --where '_Modified == 3'`` reads the method, so
  the filter matches no record (exit 0). On a message field of that name,
  ``--where '_Modified.v == 3'`` raises ``AttributeError`` instead; the pin
  holds the silent form.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner, Result
from google.protobuf import descriptor_pb2, descriptor_pool, message, message_factory, reflection
from google.protobuf.internal import api_implementation
from google.protobuf.message import Message

from protokit._pools import build_pool
from protokit.cli import main as protokit_main
from protokit.forensics import Candidate
from protokit.forensics import match as forensics_match
from protokit.message import MessageDifferencer
from protokit.message.cli import main as diff_main
from protokit.options import get_option_value
from protokit.storage import FileDescriptorSetSchema, StreamRegistry, scan

_F = descriptor_pb2.FieldDescriptorProto
_PKG = "auditcfield"
_PURE_PYTHON_BACKEND = api_implementation.Type() == "python"
#: The marker's condition for a pin that fails under upb only; the twin of
#: ``_PURE_PYTHON_BACKEND``.
_UPB_BACKEND = api_implementation.Type() == "upb"


def _paths(left: Message, right: Message, *, ignore: str | None = None) -> list[tuple[str, str]]:
    """``MessageDifferencer().compare(left, right)`` as ``(path, change)`` pairs."""
    differ = MessageDifferencer()
    if ignore is not None:
        differ.ignore_fields(ignore)
    return [(str(diff.path), diff.change_type.name) for diff in differ.compare(left, right)]


def _isolated_class(file_proto: descriptor_pb2.FileDescriptorProto, type_name: str) -> type:
    """The class of ``type_name`` from a fresh pool holding ``file_proto`` alone."""
    pool = descriptor_pool.DescriptorPool()
    pool.Add(file_proto)
    cls: type = message_factory.GetMessageClass(pool.FindMessageTypeByName(type_name))
    return cls


def _write_set(path: Path, *files: descriptor_pb2.FileDescriptorProto) -> str:
    path.write_bytes(descriptor_pb2.FileDescriptorSet(file=list(files)).SerializeToString())
    return str(path)


def _outcome(result: Result) -> str:
    return f"exit {result.exit_code}; stdout {result.stdout!r}; stderr {result.stderr!r}"


def _assert_clean_or_refused(result: Result, *names: str) -> None:
    """Exit 0, or exit 2 refusing THIS input; anything else is ``pytest.fail``.

    A refusal is an exit 2, not a usage error, whose message names one of
    ``names`` (the field, the type, or for ``diff`` the file it would not
    parse). ``pytest.fail`` is not any pin's ``raises=``, so an exit that is
    neither fixed outcome (exit 1 with a report, a usage error, an exit 2 that
    names none of them) is red rather than XPASS or "expected".
    """
    if result.exit_code == 0:
        return
    refused = (
        result.exit_code == 2
        and "Usage:" not in result.stderr
        and any(name in result.stderr for name in names)
    )
    if not refused:
        pytest.fail(f"neither a clean run nor a refusal naming {names}: {_outcome(result)}")


# ---------------------------------------------------------------------------
# C01-C5 — an element field named DESCRIPTOR fails the first option read
# ---------------------------------------------------------------------------


def _count_option_holder(element_field: str) -> object:
    """Field ``f`` whose options hold ``(odds) = [{<element_field>: 5}]`` and ``(count) = 7``.

    ``odds`` is a repeated message-typed ``FieldOptions`` extension whose
    element type ``Odd`` declares one field, ``element_field``. A fresh pool.
    """
    opts = descriptor_pb2.FileDescriptorProto(
        name="auditcfield/o.proto", package=_PKG, syntax="proto2",
        dependency=["google/protobuf/descriptor.proto"],
    )
    opts.message_type.add(name="Odd").field.add(
        name=element_field, number=1, type=_F.TYPE_INT32, label=_F.LABEL_OPTIONAL,
    )
    opts.extension.add(
        name="odds", number=50001, type=_F.TYPE_MESSAGE, label=_F.LABEL_REPEATED,
        type_name=f".{_PKG}.Odd", extendee=".google.protobuf.FieldOptions",
    )
    opts.extension.add(
        name="count", number=50002, type=_F.TYPE_INT32, label=_F.LABEL_OPTIONAL,
        extendee=".google.protobuf.FieldOptions",
    )
    holder = descriptor_pb2.FileDescriptorProto(
        name="auditcfield/t.proto", package=_PKG, syntax="proto2",
        dependency=["auditcfield/o.proto"],
    )
    # (odds) = [{ <element_field>: 5 }], (count) = 7: every byte well formed.
    holder.message_type.add(name="M").field.add(
        name="f", number=1, type=_F.TYPE_INT32, label=_F.LABEL_OPTIONAL,
    ).options.MergeFromString(bytes.fromhex("8ab518020805" "90b51807"))
    fds = descriptor_pb2.FileDescriptorSet()
    descriptor_pb2.DESCRIPTOR.CopyToProto(fds.file.add())
    fds.file.extend([opts, holder])
    return build_pool(fds).FindMessageTypeByName(f"{_PKG}.M").fields_by_name["f"]


@pytest.mark.xfail(
    condition=_PURE_PYTHON_BACKEND,
    strict=True,
    raises=AttributeError,
    reason=(
        "C01-C5: owned by U17a (0.19.0). Pure-Python only. Parsing the option bytes "
        "builds the class of the repeated option's element type, which has a field "
        "named DESCRIPTOR, and building it fails, so the first get_option_value on "
        "the descriptor raises a raw AttributeError ('_FieldProperty' object has no "
        "attribute 'extensions') where a second read returns 7"
    ),
)
def test_c01_c5_the_first_option_read_beside_an_element_field_named_descriptor() -> None:
    """Under upb this is the upb control for the pure-Python pin (see the module docstring)."""
    field = _count_option_holder("DESCRIPTOR")
    assert get_option_value(field, f"{_PKG}.count") == 7


def test_c01_c5_the_first_option_read_beside_a_renamed_element_field_control() -> None:
    # The same options, with the element's field called ``descriptor``.
    field = _count_option_holder("descriptor")
    assert get_option_value(field, f"{_PKG}.count") == 7


# ---------------------------------------------------------------------------
# C02-C3, DESCRIPTOR half — a type with a field named DESCRIPTOR, through the CLI
# ---------------------------------------------------------------------------

_SHADOW_TYPE = f"{_PKG}.Shadow"
_SHADOW_COMMANDS = ["storage-count", "forensics-drift", "forensics-match"]


def _shadow_run(tmp_path: Path, command: str, field: str) -> Result:
    """``command`` over ``message Shadow { int32 <field> = 1; }`` from a descriptor set."""
    file_proto = descriptor_pb2.FileDescriptorProto(
        name="auditcfield/shadow.proto", package=_PKG, syntax="proto3",
    )
    file_proto.message_type.add(name="Shadow").field.add(
        name=field, number=1, type=_F.TYPE_INT32, label=_F.LABEL_OPTIONAL,
    )
    desc = _write_set(tmp_path / "shadow.binpb", file_proto)
    empty, one = tmp_path / "empty.bin", tmp_path / "one.bin"
    empty.write_bytes(b"")
    one.write_bytes(b"\x08\x05")  # <field> = 5
    argv = {
        "storage-count": ["storage", "count", str(empty), "--desc", desc, "--type", _SHADOW_TYPE],
        "forensics-drift": [
            "forensics", "drift", str(one), "--schema", desc, "--type", _SHADOW_TYPE,
        ],
        "forensics-match": [
            "forensics", "match", str(one), "--schema", f"a={desc}", "--type", _SHADOW_TYPE,
        ],
    }[command]
    return CliRunner().invoke(protokit_main, argv, catch_exceptions=False)


@pytest.mark.parametrize("command", _SHADOW_COMMANDS)
@pytest.mark.xfail(
    condition=_PURE_PYTHON_BACKEND,
    strict=True,
    raises=AttributeError,
    reason=(
        "C02-C3 (DESCRIPTOR half): owned by U17a (0.19.0). Pure-Python only. "
        "get_message_class calls message_factory.GetMessageClass outside any try, and "
        "pure-Python cannot build a class with a field named DESCRIPTOR, so storage "
        "count, forensics drift and forensics match end in a raw AttributeError "
        "('_FieldProperty' object has no attribute 'extensions'). Either outcome "
        "counts as fixed: the command runs, or it exits 2 refusing the type"
    ),
)
def test_c02_c3_a_type_with_a_field_named_descriptor_runs_or_is_refused(
    tmp_path: Path, command: str,
) -> None:
    """Under upb this is the upb control for the pure-Python pin (see the module docstring)."""
    result = _shadow_run(tmp_path, command, "DESCRIPTOR")
    _assert_clean_or_refused(result, "DESCRIPTOR", _SHADOW_TYPE)


@pytest.mark.parametrize("command", _SHADOW_COMMANDS)
def test_c02_c3_a_type_with_the_field_renamed_runs_control(tmp_path: Path, command: str) -> None:
    result = _shadow_run(tmp_path, command, "descriptor")
    assert result.exit_code == 0, _outcome(result)


# ---------------------------------------------------------------------------
# C02-C7 and C02-X1 — get_option_value's sub-path walk reads attributes
# ---------------------------------------------------------------------------


def _cfg_holder(names: tuple[str, ...]) -> object:
    """Message ``M`` whose options hold ``(cfg) = {names[0]: 7, names[1]: 8, ...}``.

    ``Config`` declares one ``int32`` per name, numbered from 1, and the option
    is written as wire bytes: pure-Python cannot set a field named like a method
    by attribute. A fresh pool.
    """
    fds = descriptor_pb2.FileDescriptorSet()
    descriptor_pb2.DESCRIPTOR.CopyToProto(fds.file.add())
    file_proto = fds.file.add(
        name="auditcfield/cfg.proto", package=_PKG, syntax="proto2",
        dependency=["google/protobuf/descriptor.proto"],
    )
    config = file_proto.message_type.add(name="Config")
    body = b""
    for number, name in enumerate(names, 1):
        config.field.add(name=name, number=number, type=_F.TYPE_INT32, label=_F.LABEL_OPTIONAL)
        body += bytes([number << 3, 6 + number])
    file_proto.extension.add(
        name="cfg", number=50000, type=_F.TYPE_MESSAGE, label=_F.LABEL_OPTIONAL,
        type_name=f".{_PKG}.Config", extendee=".google.protobuf.MessageOptions",
    )
    # Tag of field 50000, length-delimited: 82 b5 18.
    file_proto.message_type.add(name="M").options.MergeFromString(
        b"\x82\xb5\x18" + bytes([len(body)]) + body,
    )
    return build_pool(fds).FindMessageTypeByName(f"{_PKG}.M")


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "C02-C7: owned by U17a (0.19.0). get_option_value walks the segments below a "
        "set message option with getattr, so a segment that names no field of Config "
        "but names a method (cfg.ByteSize) returns the bound method on both backends, "
        "where a path that names no field must read None"
    ),
)
def test_c02_c7_a_sub_path_naming_a_method_and_no_field_reads_none() -> None:
    holder = _cfg_holder(("plain",))
    assert get_option_value(holder, f"{_PKG}.cfg.ByteSize") is None


def test_c02_c7_a_sub_path_naming_nothing_reads_none_control() -> None:
    # The same option, with a segment that names neither a field nor an attribute.
    holder = _cfg_holder(("plain",))
    assert get_option_value(holder, f"{_PKG}.cfg.nope") is None
    assert get_option_value(holder, f"{_PKG}.cfg.plain") == 7


_METHOD_NAMED_SUB_FIELDS = ("SerializeToString", "ByteSize", "plain")


@pytest.mark.parametrize(("name", "value"), [("SerializeToString", 7), ("ByteSize", 8)])
@pytest.mark.xfail(
    condition=_PURE_PYTHON_BACKEND,
    strict=True,
    raises=AssertionError,
    reason=(
        "C02-X1: owned by U17a (0.19.0). Pure-Python only. get_option_value reads a "
        "sub-field below a set option with getattr, and under pure-Python a method "
        "hides a field of the same name, so (cfg).SerializeToString and (cfg).ByteSize "
        "read as bound methods instead of 7 and 8"
    ),
)
def test_c02_x1_a_sub_field_named_like_a_method_reads_its_value(name: str, value: int) -> None:
    """Under upb this is the upb control for the pure-Python pin (see the module docstring)."""
    holder = _cfg_holder(_METHOD_NAMED_SUB_FIELDS)
    assert get_option_value(holder, f"{_PKG}.cfg.{name}") == value


def test_c02_x1_a_plainly_named_sub_field_beside_them_reads_its_value_control() -> None:
    holder = _cfg_holder(_METHOD_NAMED_SUB_FIELDS)
    assert get_option_value(holder, f"{_PKG}.cfg.plain") == 9


# ---------------------------------------------------------------------------
# C10-C1b and C10-C5 — protokit diff parses into a type with a method-named field
# ---------------------------------------------------------------------------


#: The file every ``protokit diff`` here compares with itself.
_DIFF_INPUT = "a.in"


def _diff_one_field(
    tmp_path: Path, field: str, payload: bytes, *flags: str,
) -> Result:
    """``protokit diff`` of a payload against itself, ``message M { string <field> = 1; }``."""
    file_proto = descriptor_pb2.FileDescriptorProto(
        name="auditcfield/one.proto", package=_PKG, syntax="proto3",
    )
    file_proto.message_type.add(name="M").field.add(
        name=field, number=1, type=_F.TYPE_STRING, label=_F.LABEL_OPTIONAL,
    )
    desc = _write_set(tmp_path / "one.binpb", file_proto)
    data = tmp_path / _DIFF_INPUT
    data.write_bytes(payload)
    return CliRunner().invoke(
        diff_main,
        [str(data), str(data), "--desc", desc, "--message-type", f"{_PKG}.M", *flags],
        catch_exceptions=False,
    )


@pytest.mark.xfail(
    condition=_PURE_PYTHON_BACKEND,
    strict=True,
    raises=AttributeError,
    reason=(
        "C10-C1b: owned by U17a (0.19.0). Pure-Python only. _parse_message hands --json "
        "input to json_format.Parse, which sets each field by attribute, and under "
        "pure-Python a field named Clear is the read-only method, so protokit diff "
        "ends in a raw AttributeError ('M' object attribute 'Clear' is read-only). "
        "Either outcome counts as fixed: exit 0, or exit 2 refusing the type"
    ),
)
def test_c10_c1b_diff_json_on_a_field_named_clear_runs_or_is_refused(tmp_path: Path) -> None:
    """Under upb this is the upb control for the pure-Python pin (see the module docstring)."""
    result = _diff_one_field(tmp_path, "Clear", b'{"Clear": "a"}', "--json")
    _assert_clean_or_refused(result, "Clear", f"{_PKG}.M", _DIFF_INPUT)


def test_c10_c1b_diff_json_on_the_field_renamed_control(tmp_path: Path) -> None:
    result = _diff_one_field(tmp_path, "clear", b'{"clear": "a"}', "--json")
    assert result.exit_code == 0, _outcome(result)


@pytest.mark.xfail(
    strict=True,
    raises=TypeError,
    reason=(
        "C10-C5: owned by U17a (0.19.0). _parse_message calls msg.ParseFromString(data), "
        "which on a type with a field named ParseFromString is the field's value on "
        "both backends, so protokit diff of a binary file against itself ends in a raw "
        "TypeError ('str' object is not callable) instead of exit 0"
    ),
)
def test_c10_c5_diff_binary_on_a_field_named_parsefromstring_exits_0(tmp_path: Path) -> None:
    result = _diff_one_field(tmp_path, "ParseFromString", b"\x0a\x01a")
    assert result.exit_code == 0, _outcome(result)


def test_c10_c5_diff_binary_on_the_field_renamed_control(tmp_path: Path) -> None:
    result = _diff_one_field(tmp_path, "parse_from_string", b"\x0a\x01a")
    assert result.exit_code == 0, _outcome(result)


# ---------------------------------------------------------------------------
# C14-C1 — scan parses each record through the instance's MergeFromString
# ---------------------------------------------------------------------------


def _id_and_field_registry(field: str) -> StreamRegistry:
    """Stream ``s``: proto3 ``message M { int32 id = 1; int32 <field> = 2; }``."""
    fds = descriptor_pb2.FileDescriptorSet()
    file_proto = fds.file.add(name="auditcfield/scan.proto", package=_PKG, syntax="proto3")
    msg = file_proto.message_type.add(name="M")
    msg.field.add(name="id", number=1, type=_F.TYPE_INT32, label=_F.LABEL_OPTIONAL)
    msg.field.add(name=field, number=2, type=_F.TYPE_INT32, label=_F.LABEL_OPTIONAL)
    registry = StreamRegistry()
    registry.register_stream("s", FileDescriptorSetSchema(fds, f"{_PKG}.M"))
    return registry


# M{id: 7}, M{id: 8, <field>: 1}
_TWO_RECORDS = [("s", b"\x08\x07"), ("s", b"\x08\x08\x10\x01")]


@pytest.mark.parametrize("on_error", ["raise", "skip", "collect"])
@pytest.mark.xfail(
    condition=_UPB_BACKEND,
    strict=True,
    raises=TypeError,
    reason=(
        "C14-C1: owned by U17a (0.19.0). upb only. The scan engine parses each record "
        "with message.MergeFromString, which on a type with a field of that name is the "
        "field's value under upb, so every record raises a raw TypeError ('int' object "
        "is not callable) that escapes every on_error mode, where pure-Python yields "
        "both records"
    ),
)
def test_c14_c1_scan_a_type_with_a_field_named_mergefromstring(on_error: str) -> None:
    """Under pure-Python this is the pure-Python control for the upb pin (module docstring)."""
    registry = _id_and_field_registry("MergeFromString")
    ids = [record.message.id for record in scan(iter(_TWO_RECORDS), registry, on_error=on_error)]
    assert ids == [7, 8]


def test_c14_c1_scan_the_field_renamed_control() -> None:
    registry = _id_and_field_registry("merge_from_string")
    assert [record.message.id for record in scan(iter(_TWO_RECORDS), registry)] == [7, 8]


# ---------------------------------------------------------------------------
# C17-C6 — forensics.match on a candidate with a method-named field
# ---------------------------------------------------------------------------


def _match_one(field: str) -> tuple[str, str]:
    """``(verdict, parse outcome)`` of matching ``x = 5, field 2 = 7`` against one candidate.

    The candidate is proto3 ``message A { int32 x = 1; int32 <field> = 2; }``.
    """
    file_proto = descriptor_pb2.FileDescriptorProto(
        name="auditcfield/a.proto", package=_PKG, syntax="proto3",
    )
    msg = file_proto.message_type.add(name="A")
    msg.field.add(name="x", number=1, type=_F.TYPE_INT32, label=_F.LABEL_OPTIONAL)
    msg.field.add(name=field, number=2, type=_F.TYPE_INT32, label=_F.LABEL_OPTIONAL)
    fds = descriptor_pb2.FileDescriptorSet(file=[file_proto])
    schema = FileDescriptorSetSchema(fds, f"{_PKG}.A")
    report = forensics_match(b"\x08\x05\x10\x07", [Candidate(field, schema)])
    return report.verdict, report.ranked[0].parse_outcome


@pytest.mark.parametrize(
    "field", ["MergeFromString", "ListFields", "ByteSize", "DiscardUnknownFields"],
)
@pytest.mark.xfail(
    condition=_UPB_BACKEND,
    strict=True,
    raises=TypeError,
    reason=(
        "C17-C6: owned by U17a (0.19.0). upb only. The fit calls message.MergeFromString "
        "and message.ListFields, and the fidelity probe ByteSize and DiscardUnknownFields, "
        "on the instance, where under upb a field of that name is the field's value, so "
        "the whole ranking aborts with a raw TypeError ('int' object is not callable) "
        "where pure-Python ranks the candidate a clean winner"
    ),
)
def test_c17_c6_match_ranks_a_candidate_with_a_method_named_field(field: str) -> None:
    """Under pure-Python this is the pure-Python control for the upb pin (module docstring)."""
    assert _match_one(field) == ("clean_winner", "clean")


@pytest.mark.xfail(
    strict=True,
    raises=TypeError,
    reason=(
        "C17-C6 (CopyFrom): owned by U17a (0.19.0). The fidelity probe calls "
        "clone.CopyFrom(message), which on a type with a field named CopyFrom is the "
        "field's value on both backends, so the ranking aborts with a raw TypeError "
        "('int' object is not callable)"
    ),
)
def test_c17_c6_match_ranks_a_candidate_with_a_field_named_copyfrom() -> None:
    assert _match_one("CopyFrom") == ("clean_winner", "clean")


def test_c17_c6_match_ranks_the_candidate_with_the_field_renamed_control() -> None:
    assert _match_one("copy_from") == ("clean_winner", "clean")


# ---------------------------------------------------------------------------
# C14-C3 — the columnar sinks check message.DESCRIPTOR on the instance
# ---------------------------------------------------------------------------


def _columnar_rows(tmp_path: Path, field: str) -> tuple[list[dict[str, object]], int]:
    """``(to_parquet rows read back, to_arrow_batches row count)`` over ``_TWO_RECORDS``."""
    pytest.importorskip("pyarrow")
    pytest.importorskip("ptars")
    import pyarrow.parquet as pq

    from protokit.storage import to_arrow_batches, to_parquet

    registry = _id_and_field_registry(field)
    out = tmp_path / "o.parquet"
    to_parquet(list(_TWO_RECORDS), registry, out, stream_id="s")
    batches = to_arrow_batches(list(_TWO_RECORDS), registry, stream_id="s")
    return pq.read_table(out).to_pylist(), sum(batch.num_rows for batch in batches)


@pytest.mark.skipif(
    _PURE_PYTHON_BACKEND,
    reason="pure-Python cannot build a class with a field named DESCRIPTOR (C02-C3, pinned above)",
)
@pytest.mark.xfail(
    condition=_UPB_BACKEND,
    strict=True,
    raises=AttributeError,
    reason=(
        "C14-C3: owned by U17a (0.19.0). upb only. to_record_batch checks "
        "message.DESCRIPTOR, which on a type with a field named DESCRIPTOR is the "
        "field's value under upb, so to_parquet and to_arrow_batches raise a raw "
        "AttributeError ('int' object has no attribute 'full_name')"
    ),
)
def test_c14_c3_the_columnar_sinks_convert_a_type_with_a_field_named_descriptor(
    tmp_path: Path,
) -> None:
    rows, batch_rows = _columnar_rows(tmp_path, "DESCRIPTOR")
    assert rows == [{"id": 7, "DESCRIPTOR": 0}, {"id": 8, "DESCRIPTOR": 1}]
    assert batch_rows == 2


def test_c14_c3_the_columnar_sinks_convert_the_field_renamed_control(tmp_path: Path) -> None:
    rows, batch_rows = _columnar_rows(tmp_path, "descriptor")
    assert rows == [{"id": 7, "descriptor": 0}, {"id": 8, "descriptor": 1}]
    assert batch_rows == 2


# ---------------------------------------------------------------------------
# C04-X5, what the 0.16.0 fix left — the differ's other reads of ListFields
# ---------------------------------------------------------------------------


def _list_fields_classes(field: str) -> tuple[type, type]:
    """proto2 ``M { optional string <field> = 1; }`` and ``O { optional M m = 1; }``."""
    file_proto = descriptor_pb2.FileDescriptorProto(
        name="auditcfield/lf.proto", package=_PKG, syntax="proto2",
    )
    file_proto.message_type.add(name="M").field.add(
        name=field, number=1, type=_F.TYPE_STRING, label=_F.LABEL_OPTIONAL,
    )
    file_proto.message_type.add(name="O").field.add(
        name="m", number=1, type=_F.TYPE_MESSAGE, label=_F.LABEL_OPTIONAL,
        type_name=f".{_PKG}.M",
    )
    pool = descriptor_pool.DescriptorPool()
    pool.Add(file_proto)
    return (
        message_factory.GetMessageClass(pool.FindMessageTypeByName(f"{_PKG}.M")),
        message_factory.GetMessageClass(pool.FindMessageTypeByName(f"{_PKG}.O")),
    )


@pytest.mark.xfail(
    condition=_PURE_PYTHON_BACKEND,
    strict=True,
    raises=AssertionError,
    reason=(
        "C04-X5 (pure-Python residue): owned by U17a (0.19.0). Pure-Python only. The "
        "differ reads a declared field with getattr, and under pure-Python the method "
        "hides a field named ListFields, so two identical messages compare two "
        "different bound methods and are reported ('ListFields', 'MODIFIED')"
    ),
)
def test_c04_x5_identical_messages_with_a_field_named_listfields_compare_equal() -> None:
    """Under upb this is the upb control for the pure-Python pin (see the module docstring)."""
    m_class, _ = _list_fields_classes("ListFields")
    assert _paths(m_class.FromString(b"\x0a\x01x"), m_class.FromString(b"\x0a\x01x")) == []


@pytest.mark.xfail(
    condition=_UPB_BACKEND,
    strict=True,
    raises=TypeError,
    reason=(
        "C04-X5 (upb residue): owned by U17a (0.19.0). upb only. The one-sided route "
        "(_has_populated_fields, then _emit_all_fields) calls msg.ListFields() on a "
        "message set on one side only, and under upb a field named ListFields is the "
        "field's value, so compare raises a raw TypeError ('str' object is not callable) "
        "where pure-Python reports m.ListFields ADDED"
    ),
)
def test_c04_x5_a_subtree_with_a_field_named_listfields_set_on_one_side() -> None:
    """Under pure-Python this is the pure-Python control for the upb pin (module docstring)."""
    _, o_class = _list_fields_classes("ListFields")
    left, right = o_class(), o_class.FromString(b"\x0a\x03\x0a\x01x")
    assert _paths(left, right) == [("m.ListFields", "ADDED")]


def test_c04_x5_the_field_renamed_control() -> None:
    m_class, o_class = _list_fields_classes("list_fields")
    assert _paths(m_class.FromString(b"\x0a\x01x"), m_class.FromString(b"\x0a\x01x")) == []
    left, right = o_class(), o_class.FromString(b"\x0a\x03\x0a\x01x")
    assert _paths(left, right) == [("m.list_fields", "ADDED")]


# ---------------------------------------------------------------------------
# No finding ID — a field named Extensions, read by compare under pure-Python
# ---------------------------------------------------------------------------

_NO_ID = "No finding ID (field-name family): owned by U17a (0.19.0). "


def _extensions_field_file(field: str) -> descriptor_pb2.FileDescriptorProto:
    """proto2 ``M { optional string <field> = 1; optional int32 id = 2; extensions 100 to 199; }``.

    The file also declares ``extend M { optional int32 ext = 100; }``.
    """
    file_proto = descriptor_pb2.FileDescriptorProto(
        name="auditcfield/ext.proto", package=_PKG, syntax="proto2",
    )
    msg = file_proto.message_type.add(name="M")
    msg.field.add(name=field, number=1, type=_F.TYPE_STRING, label=_F.LABEL_OPTIONAL)
    msg.field.add(name="id", number=2, type=_F.TYPE_INT32, label=_F.LABEL_OPTIONAL)
    msg.extension_range.add(start=100, end=200)
    file_proto.extension.add(
        name="ext", number=100, type=_F.TYPE_INT32, label=_F.LABEL_OPTIONAL,
        extendee=f".{_PKG}.M",
    )
    return file_proto


@pytest.mark.xfail(
    condition=_PURE_PYTHON_BACKEND,
    strict=True,
    raises=AttributeError,
    reason=_NO_ID + (
        "Pure-Python only. The differ reads a declared field with getattr, and under "
        "pure-Python the extension mapping hides a field named Extensions, so compare "
        "compares two extension mappings and raises a raw AttributeError ('tuple' "
        "object has no attribute 'is_extension') unless that field is ignored"
    ),
)
def test_compare_reads_a_field_named_extensions() -> None:
    """Under upb this is the upb control for the pure-Python pin (see the module docstring)."""
    cls = _isolated_class(_extensions_field_file("Extensions"), f"{_PKG}.M")
    left, right = cls.FromString(b"\x0a\x01a"), cls.FromString(b"\x0a\x01b")
    assert _paths(left, right) == [("Extensions", "MODIFIED")]


def test_compare_reads_a_field_named_extensions_when_ignored_control() -> None:
    # The same schema and payloads: ignored, the field is never read, on both backends.
    cls = _isolated_class(_extensions_field_file("Extensions"), f"{_PKG}.M")
    left, right = cls.FromString(b"\x0a\x01a"), cls.FromString(b"\x0a\x01b")
    assert _paths(left, right, ignore="Extensions") == []


def test_compare_reads_the_field_renamed_control() -> None:
    cls = _isolated_class(_extensions_field_file("extensions"), f"{_PKG}.M")
    left, right = cls.FromString(b"\x0a\x01a"), cls.FromString(b"\x0a\x01b")
    assert _paths(left, right) == [("extensions", "MODIFIED")]


# ---------------------------------------------------------------------------
# No finding ID — an underscore-named message field, read by compare under pure-Python
# ---------------------------------------------------------------------------


def _private_message_field_class(field: str) -> type:
    """proto2 ``M { optional S <field> = 1; }``, ``S { optional int32 v = 1; }``."""
    file_proto = descriptor_pb2.FileDescriptorProto(
        name="auditcfield/private.proto", package=_PKG, syntax="proto2",
    )
    file_proto.message_type.add(name="S").field.add(
        name="v", number=1, type=_F.TYPE_INT32, label=_F.LABEL_OPTIONAL,
    )
    file_proto.message_type.add(name="M").field.add(
        name=field, number=1, type=_F.TYPE_MESSAGE, label=_F.LABEL_OPTIONAL,
        type_name=f".{_PKG}.S",
    )
    return _isolated_class(file_proto, f"{_PKG}.M")


@pytest.mark.parametrize("field", ["_Modified", "__str__"])
@pytest.mark.xfail(
    condition=_PURE_PYTHON_BACKEND,
    strict=True,
    raises=AttributeError,
    reason=_NO_ID + (
        "Pure-Python only. The differ reads a declared message field with getattr, and "
        "under pure-Python the method hides a field named _Modified or __str__, so "
        "compare descends into a function and raises a raw AttributeError ('function' "
        "object has no attribute 'DESCRIPTOR')"
    ),
)
def test_compare_descends_into_an_underscore_named_message_field(field: str) -> None:
    """Under upb this is the upb control for the pure-Python pin (see the module docstring)."""
    cls = _private_message_field_class(field)
    left, right = cls.FromString(b"\x0a\x02\x08\x01"), cls.FromString(b"\x0a\x02\x08\x02")
    assert _paths(left, right) == [(f"{field}.v", "MODIFIED")]


def test_compare_descends_into_the_field_renamed_control() -> None:
    cls = _private_message_field_class("modified")
    left, right = cls.FromString(b"\x0a\x02\x08\x01"), cls.FromString(b"\x0a\x02\x08\x02")
    assert _paths(left, right) == [("modified.v", "MODIFIED")]


# ---------------------------------------------------------------------------
# No finding ID — upb: protobuf's text and JSON parsers read the member a field hides
# ---------------------------------------------------------------------------


def _diff_extension_input(tmp_path: Path, field: str, text: str, form: str) -> Result:
    """``protokit diff`` of ``text`` against itself, ``field`` ignored (schema: above)."""
    desc = _write_set(tmp_path / "ext.binpb", _extensions_field_file(field))
    data = tmp_path / _DIFF_INPUT
    data.write_text(text)
    return CliRunner().invoke(
        diff_main,
        [
            str(data), str(data), "--desc", desc, "--message-type", f"{_PKG}.M",
            form, "--ignore", field,
        ],
        catch_exceptions=False,
    )


_SET_EXTENSION = {
    "--text-format": f"id: 1 [{_PKG}.ext]: 3",
    "--json": f'{{"id": 1, "[{_PKG}.ext]": 3}}',
}


@pytest.mark.parametrize("form", ["--text-format", "--json"])
@pytest.mark.xfail(
    condition=_UPB_BACKEND,
    strict=True,
    raises=AttributeError,
    reason=_NO_ID + (
        "upb only. text_format.Parse and json_format.Parse resolve a set extension "
        "through message.Extensions, which under upb is the value of a field named "
        "Extensions, so protokit diff of input that sets an extension ends in a raw "
        "AttributeError ('str' object has no attribute '_FindExtensionByName'). Either "
        "outcome counts as fixed: exit 0, or exit 2 refusing the type"
    ),
)
def test_diff_text_or_json_setting_an_extension_beside_a_field_named_extensions(
    tmp_path: Path, form: str,
) -> None:
    """Under pure-Python this is the pure-Python control for the upb pin (module docstring)."""
    result = _diff_extension_input(tmp_path, "Extensions", _SET_EXTENSION[form], form)
    _assert_clean_or_refused(result, "Extensions", f"{_PKG}.M", _DIFF_INPUT)


@pytest.mark.xfail(
    condition=_UPB_BACKEND,
    strict=True,
    raises=TypeError,
    reason=_NO_ID + (
        "upb only. text_format.Parse calls message.HasExtension for a set extension, "
        "which under upb is the value of a field named HasExtension, so protokit diff "
        "--text-format of input that sets an extension ends in a raw TypeError ('str' "
        "object is not callable). Either outcome counts as fixed: exit 0, or exit 2 "
        "refusing the type"
    ),
)
def test_diff_text_setting_an_extension_beside_a_field_named_hasextension(tmp_path: Path) -> None:
    """Under pure-Python this is the pure-Python control for the upb pin (module docstring)."""
    result = _diff_extension_input(
        tmp_path, "HasExtension", _SET_EXTENSION["--text-format"], "--text-format",
    )
    _assert_clean_or_refused(result, "HasExtension", f"{_PKG}.M", _DIFF_INPUT)


@pytest.mark.parametrize("form", ["--text-format", "--json"])
def test_diff_text_or_json_setting_an_extension_beside_the_field_renamed_control(
    tmp_path: Path, form: str,
) -> None:
    result = _diff_extension_input(tmp_path, "extensions", _SET_EXTENSION[form], form)
    assert result.exit_code == 0, _outcome(result)


# ---------------------------------------------------------------------------
# No finding ID — upb: a generated-style class with a nested type named HasField
# ---------------------------------------------------------------------------


def _generated_style(desc: object) -> type:
    """The class a generated module builds: nested classes in the class dictionary."""
    members: dict[str, object] = {
        name: _generated_style(nested)
        for name, nested in desc.nested_types_by_name.items()  # type: ignore[attr-defined]
    }
    members.update(DESCRIPTOR=desc, __module__="auditcfield_pb2")
    cls: type = reflection.GeneratedProtocolMessageType(
        desc.name, (message.Message,), members,  # type: ignore[attr-defined]
    )
    return cls


def _query_class(nested: str) -> type:
    """proto2 ``Query { message <nested> { optional int32 page = 1; } optional int32 x = 1; }``."""
    file_proto = descriptor_pb2.FileDescriptorProto(
        name="auditcfield/q.proto", package=_PKG, syntax="proto2",
    )
    query = file_proto.message_type.add(name="Query")
    query.nested_type.add(name=nested).field.add(
        name="page", number=1, type=_F.TYPE_INT32, label=_F.LABEL_OPTIONAL,
    )
    query.field.add(name="x", number=1, type=_F.TYPE_INT32, label=_F.LABEL_OPTIONAL)
    pool = descriptor_pool.DescriptorPool()
    pool.Add(file_proto)
    return _generated_style(pool.FindMessageTypeByName(f"{_PKG}.Query"))


@pytest.mark.xfail(
    condition=_UPB_BACKEND,
    strict=True,
    raises=TypeError,
    reason=_NO_ID + (
        "upb only. field_present asks msg.HasField(name) for a declared field, and a "
        "generated class keeps a nested type named HasField in its own dictionary, so "
        "under upb compare calls the nested class and raises a raw TypeError (No "
        "positional arguments allowed) where pure-Python reports x MODIFIED"
    ),
)
def test_compare_a_generated_class_with_a_nested_type_named_hasfield() -> None:
    """Under pure-Python this is the pure-Python control for the upb pin (module docstring)."""
    cls = _query_class("HasField")
    assert _paths(cls.FromString(b"\x08\x05"), cls.FromString(b"\x08\x06")) == [("x", "MODIFIED")]


def test_compare_a_generated_class_with_the_nested_type_renamed_control() -> None:
    cls = _query_class("Filter")
    assert _paths(cls.FromString(b"\x08\x05"), cls.FromString(b"\x08\x06")) == [("x", "MODIFIED")]


# ---------------------------------------------------------------------------
# No finding ID — pure-Python: storage scan --where reads an underscore field by name
# ---------------------------------------------------------------------------


def _scan_where(tmp_path: Path, field: str) -> list[int]:
    """Ids ``storage scan --where '<field> == 3' --format json`` prints over two records.

    proto3 ``message M { int32 id = 1; int32 <field> = 2; }``; the records are
    ``{id: 7, <field>: 3}`` and ``{id: 8}``, length-prefixed.
    """
    file_proto = descriptor_pb2.FileDescriptorProto(
        name="auditcfield/where.proto", package=_PKG, syntax="proto3",
    )
    msg = file_proto.message_type.add(name="M")
    msg.field.add(name="id", number=1, type=_F.TYPE_INT32, label=_F.LABEL_OPTIONAL)
    msg.field.add(name=field, number=2, type=_F.TYPE_INT32, label=_F.LABEL_OPTIONAL)
    desc = _write_set(tmp_path / "where.binpb", file_proto)
    data = tmp_path / "records.bin"
    data.write_bytes(b"".join(bytes([len(r)]) + r for r in (b"\x08\x07\x10\x03", b"\x08\x08")))
    result = CliRunner().invoke(
        protokit_main,
        [
            "storage", "scan", str(data), "--desc", desc, "--type", f"{_PKG}.M",
            "--where", f"{field} == 3", "--format", "json",
        ],
        catch_exceptions=False,
    )
    if result.exit_code != 0:
        # Not this pin's defect (a bad filter, a load that failed): red, never "expected".
        pytest.fail(f"storage scan did not run: {_outcome(result)}")
    return [json.loads(line)["id"] for line in result.stdout.splitlines() if line.strip()]


@pytest.mark.xfail(
    condition=_PURE_PYTHON_BACKEND,
    strict=True,
    raises=AssertionError,
    reason=_NO_ID + (
        "Pure-Python only. The --where getter reads each path segment with getattr, and "
        "under pure-Python the method hides a field named _Modified, so '_Modified == 3' "
        "compares a bound method with 3 and the filter matches no record, exit 0"
    ),
)
def test_storage_scan_where_on_a_field_named_modified_matches_the_record(tmp_path: Path) -> None:
    """Under upb this is the upb control for the pure-Python pin (see the module docstring)."""
    assert _scan_where(tmp_path, "_Modified") == [7]


def test_storage_scan_where_on_the_field_renamed_control(tmp_path: Path) -> None:
    assert _scan_where(tmp_path, "modified") == [7]
