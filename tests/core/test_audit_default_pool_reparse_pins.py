"""Strict-xfail pins: a schema's file is still parsed through the default pool.

Found 2026-10-11, after the 0.16.0 re-audit, while fixing what ``GetOptions()``
does under upb (``protokit._extensions.options_of``). The re-parse itself has
no audit finding ID; U25 owns it, first in 0.18.0, with C15-T1 and C15-T2.

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

The same re-parse happens in ``protokit._descriptors._file_message_index``
(``check_compatibility``, and the tie-break of a ``forensics match``), the lint
engine's import graph and the lint rules in ``rules/file.py``,
``rules/imports.py`` and ``rules/field.py``. ``protokit._fieldview`` reads no
file back any more: its string walk asks each field. Its one read left that
depends on the default pool is ``is_map_field``, which calls ``GetOptions()``.
The two loaders, ``check_compatibility``, ``protokit lint`` (through its loader
and its import graph) and a tied ``forensics match`` are measured here.

Registering an extension in the default pool cannot be undone, so every
scenario runs in a fresh interpreter. Each pin asserts the outcome a correct
implementation produces and is narrowed to ``AssertionError``: a scenario that
does not run raises ``RuntimeError`` and turns the pin red. The C15 and
tied-match pins raise it too for an outcome that is neither the defect's nor
the fix's.

Pinned here (every pin is owned by U25, 0.18.0):

* **The re-parse** (no finding ID) — a set loaded after an unrelated extension
  took one of its option numbers is refused by both loaders, or loaded with the
  value rewritten; ``check_compatibility`` raises ``DecodeError`` on a schema
  loaded before it.
* **C15-T1** — a ``repeated bool`` registered at 1052 before ``protokit lint``
  loads the set makes ``options/field-behavior-consistent`` report what the
  loader rewrote: ``OPTIONAL, REQUIRED`` lints as a duplicate ``OPTIONAL``, and
  a clean ``REQUIRED, IMMUTABLE`` gets the same finding.
* **C15-T2** — pure-Python only: a string registered at 1052 after the load (by
  a rule pack's import), on a field whose bytes there are a truncated payload,
  makes the lint engine's import graph raise ``UnicodeDecodeError`` outside any
  rule; ``lint`` exits 1 on a traceback where upb exits 2 with the rule's
  ``rule_exception``. Under upb the marker does not apply and the pin runs as an
  ordinary passing test: the upb control for the pure-Python pin.
* **A tied ``forensics match``** (no finding ID) — two candidates built before
  the registration tie, and the tie-break copies each file back to a proto,
  which raises ``DecodeError`` out of ``match``. One candidate never reaches the
  tie-break and is read correctly (``tests/core/test_extensions_default_pool.py``).
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
from google.protobuf.internal import api_implementation

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
_REPARSE = (
    "No finding ID: owned by U25 (0.18.0); found 2026-10-11, after the 0.16.0 re-audit. "
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
    reason=_REPARSE + (
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
    reason=_REPARSE + (
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
    reason=_REPARSE + (
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


@functools.cache
def _in_a_fresh_interpreter(script: str, *args: str) -> Any:
    """What ``script`` printed last, run with ``args`` and a scratch directory as its argv."""
    with tempfile.TemporaryDirectory() as scratch:
        result = subprocess.run(
            [sys.executable, "-c", script, *args, scratch],
            capture_output=True, text=True, check=False, timeout=300,
            env={**os.environ, "PYTHONPATH": str(_SRC)},
        )
    if result.returncode != 0:
        # Not an assertion: a pin that expects AssertionError must not accept this.
        raise RuntimeError(f"scenario {args!r} did not run:\n{result.stderr}")
    return json.loads(result.stdout.strip().splitlines()[-1])


# ---------------------------------------------------------------------------
# C15-T1 and C15-T2: ``protokit lint`` and google.api.field_behavior (1052)
# ---------------------------------------------------------------------------

# argv: registration, schema, scratch directory. Runs ``protokit lint`` on the
# schema and prints one JSON object: what escaped the run, or what it reported.
_LINTED = r"""
import json
import sys
from pathlib import Path

from click.testing import CliRunner
from google.protobuf import descriptor_pb2 as d, descriptor_pool as dp

from protokit.cli import main

FD = d.FieldDescriptorProto
RULE = "options/field-behavior-consistent"
registration, schema, scratch = sys.argv[1], sys.argv[2], Path(sys.argv[3])


def varint(n):
    out = bytearray()
    while n > 0x7F:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    out.append(n)
    return bytes(out)


def clash(kind, label):
    # An unrelated FieldOptions extension at google.api.field_behavior's number.
    f = d.FileDescriptorProto(
        name="theirs/clash.proto", package="theirs", syntax="proto2",
        dependency=["google/protobuf/descriptor.proto"],
    )
    f.extension.add(
        name="clash", number=1052, type=kind, label=label,
        extendee=".google.protobuf.FieldOptions",
    )
    return f.SerializeToString()


behavior = d.FileDescriptorProto(
    name="google/api/field_behavior.proto", package="google.api", syntax="proto3",
    dependency=["google/protobuf/descriptor.proto"],
)
enum = behavior.enum_type.add(name="FieldBehavior")
for number, value_name in enumerate((
    "FIELD_BEHAVIOR_UNSPECIFIED", "OPTIONAL", "REQUIRED", "OUTPUT_ONLY", "INPUT_ONLY",
    "IMMUTABLE",
)):
    enum.value.add(name=value_name, number=number)
behavior.extension.add(
    name="field_behavior", number=1052, type=FD.TYPE_ENUM, label=FD.LABEL_REPEATED,
    type_name=".google.api.FieldBehavior", extendee=".google.protobuf.FieldOptions",
)
TAG = varint(1052 << 3)
user = d.FileDescriptorProto(
    name="acme/v1/user.proto", package="acme.v1", syntax="proto3",
    dependency=["google/api/field_behavior.proto"],
)
user.message_type.add(name="User").field.add(
    name="name", number=1, type=FD.TYPE_STRING, label=FD.LABEL_OPTIONAL,
).options.MergeFromString({
    "OPTIONAL,REQUIRED": TAG + varint(1) + TAG + varint(2),
    "REQUIRED,IMMUTABLE": TAG + varint(2) + TAG + varint(5),
    # One length-delimited record at 1052 whose only byte starts a varint.
    "truncated": varint(1052 << 3 | 2) + varint(1) + b"\x80",
}[schema])
fds = d.FileDescriptorSet()
d.DESCRIPTOR.CopyToProto(fds.file.add())
fds.file.extend([behavior, user])
path = scratch / "set.binpb"
path.write_bytes(fds.SerializeToString())

# A rule pack with no rules. lint imports it after the set is loaded and before
# any rule runs; for "late-string" that import registers a string at 1052, the
# way a pack that imports its own generated _pb2 module does.
late = clash(FD.TYPE_STRING, FD.LABEL_OPTIONAL) if registration == "late-string" else None
(scratch / "late_pack.py").write_text(
    "from google.protobuf import descriptor_pool\n"
    f"if {late!r} is not None:\n"
    f"    descriptor_pool.Default().AddSerializedFile({late!r})\n"
    "RULES = ()\n"
)
sys.path.insert(0, str(scratch))
if registration == "early-bool":
    dp.Default().AddSerializedFile(clash(FD.TYPE_BOOL, FD.LABEL_REPEATED))
elif registration not in ("nothing", "late-string"):
    raise SystemExit(f"unknown registration {registration!r}")

argv = [
    "lint", "--no-config", "--profile", "default", "--exclude", "google/**",
    "--format", "json", "--rule-pack", "late_pack", str(path),
]
try:
    result = CliRunner().invoke(main, argv, catch_exceptions=False)
except Exception as exc:
    # The crash is an outcome to report; a non-zero exit means "did not run".
    print(json.dumps({"raised": type(exc).__name__}))
    raise SystemExit(0)
report = json.loads(result.stdout)
print(json.dumps({
    "exit": result.exit_code,
    "errors": [
        line.split(":")[0] for line in result.stderr.splitlines() if line.startswith("error[")
    ],
    "behavior": [
        [
            x["violation_kind"].rsplit("/", 1)[-1],
            {k: v for k, v in x["params"].items() if k != "field_name"},
        ]
        for x in report["findings"] if x["rule_id"] == RULE
    ],
    "warnings": [
        [w["category"], w.get("rule_id"), w.get("exception_type")]
        for w in report["runtime_warnings"]
    ],
}))
"""

_FIELD_BEHAVIOR_RULE = "options/field-behavior-consistent"
# What the rule reports for each schema while the default pool declares nothing.
_FIELD_BEHAVIOR_AS_WRITTEN = {
    "OPTIONAL,REQUIRED": [["contradictory-pair", {"value_a": "OPTIONAL", "value_b": "REQUIRED"}]],
    "REQUIRED,IMMUTABLE": [],
}
# What it reports for either schema after a repeated bool took 1052 before the load.
_FIELD_BEHAVIOR_AS_REWRITTEN = [["duplicate-value", {"value": "OPTIONAL"}]]


def _field_behavior_lint(registration: str, schema: str) -> Any:
    """The rule's findings, from a lint run that completed and reported no error."""
    outcome = _in_a_fresh_interpreter(_LINTED, registration, schema)
    if "raised" in outcome or outcome["errors"] or outcome["warnings"]:
        # Not an assertion: a run that did not complete is neither the defect nor the fix.
        raise RuntimeError(f"lint did not complete cleanly: {outcome!r}")
    return outcome["behavior"]


@pytest.mark.parametrize("schema", _FIELD_BEHAVIOR_AS_WRITTEN)
def test_c15_t1_field_behavior_lints_as_written_while_the_default_pool_declares_nothing_control(
    schema: str,
) -> None:
    assert _field_behavior_lint("nothing", schema) == _FIELD_BEHAVIOR_AS_WRITTEN[schema]


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "C15-T1: owned by U25 (0.18.0). lint's loader parses the set with a "
        "descriptor_pb2 class, which decodes 1052 as the repeated bool the default pool "
        "declares there and stores OPTIONAL, REQUIRED (01 02) as 01 01, so "
        "options/field-behavior-consistent reports a duplicate OPTIONAL instead of the "
        "contradictory pair, and flags a clean REQUIRED, IMMUTABLE. Both backends."
    ),
)
@pytest.mark.parametrize("schema", _FIELD_BEHAVIOR_AS_WRITTEN)
def test_c15_t1_field_behavior_lints_as_written_whatever_the_default_pool_declared_first(
    schema: str,
) -> None:
    got = _field_behavior_lint("early-bool", schema)
    if got not in (_FIELD_BEHAVIOR_AS_WRITTEN[schema], _FIELD_BEHAVIOR_AS_REWRITTEN):
        raise RuntimeError(f"neither the defect nor the fix: {got!r}")
    assert got == _FIELD_BEHAVIOR_AS_WRITTEN[schema]


# What lint does with the truncated record while the default pool declares
# nothing: the rule raises, the run is reported incomplete and exits 2.
_A_RULE_FAILED_ON_THE_TRUNCATED_RECORD = {
    "exit": 2,
    "errors": ["error[lint-analysis-incomplete]"],
    "behavior": [],
    "warnings": [["rule_exception", _FIELD_BEHAVIOR_RULE, "DecodeError"]],
}

_PURE_PYTHON_BACKEND = api_implementation.Type() == "python"


def test_c15_t2_a_truncated_field_behavior_fails_only_its_rule_with_nothing_registered_control(
) -> None:
    outcome = _in_a_fresh_interpreter(_LINTED, "nothing", "truncated")
    assert outcome == _A_RULE_FAILED_ON_THE_TRUNCATED_RECORD


@pytest.mark.xfail(
    condition=_PURE_PYTHON_BACKEND,
    strict=True,
    raises=AssertionError,
    reason=(
        "C15-T2: owned by U25 (0.18.0). Pure-Python only. The lint engine's import "
        "graph (engine.py, _build_import_graph_accumulator) copies each file back to a "
        "FileDescriptorProto and catches only DecodeError; the pure-Python runtime "
        "decodes 1052 as the string a rule pack registered after the load and raises "
        "UnicodeDecodeError on the truncated record, so lint exits 1 on a traceback "
        "outside any rule instead of exiting 2 with the rule's rule_exception"
    ),
)
def test_c15_t2_a_late_registration_fails_a_rule_not_the_run() -> None:
    """A string registered at 1052 after the load: still exit 2, with the rule's rule_exception.

    Under upb the marker does not apply and this is an ordinary passing test:
    it is the upb control for the pure-Python pin.
    """
    outcome = _in_a_fresh_interpreter(_LINTED, "late-string", "truncated")
    raised = outcome.get("raised")
    if raised not in (None, "UnicodeDecodeError"):
        raise RuntimeError(f"neither the defect nor the fix: {outcome!r}")
    assert raised is None, "UnicodeDecodeError escaped the lint run"
    # The record is corrupt on purpose, so the fix is the exit path, not a
    # verdict: other rules that copy the file back may fail beside this one.
    expected = _A_RULE_FAILED_ON_THE_TRUNCATED_RECORD
    if (
        (outcome["exit"], outcome["errors"]) != (expected["exit"], expected["errors"])
        or expected["warnings"][0] not in outcome["warnings"]
    ):
        raise RuntimeError(f"the crash is gone, but the run is not the fix: {outcome!r}")


# ---------------------------------------------------------------------------
# A tied ``forensics match``: the tie-break copies each file back to a proto
# ---------------------------------------------------------------------------

# argv: scenario name, scratch directory. Prints one JSON object.
_TIED_MATCH = r"""
import json
import sys

from google.protobuf import descriptor_pb2 as d, descriptor_pool as dp
from google.protobuf.message import DecodeError

from protokit.forensics._match import Candidate, match
from protokit.storage import FileDescriptorSetSchema

FD = d.FieldDescriptorProto
scenario = sys.argv[1]


def options_file(package, ext_name, kind, type_name=None):
    f = d.FileDescriptorProto(
        name=f"{package}/opts.proto", package=package, syntax="proto2",
        dependency=["google/protobuf/descriptor.proto"],
    )
    f.message_type.add(name="Info").field.add(
        name="s", number=1, type=FD.TYPE_STRING, label=FD.LABEL_OPTIONAL,
    )
    f.extension.add(
        name=ext_name, number=70001, type=kind, label=FD.LABEL_OPTIONAL, type_name=type_name,
        extendee=".google.protobuf.FieldOptions",
    )
    return f


# The schema is built, its option bytes parsed, before the default pool learns
# anything: string s = 1 [(mine.label) = "hello world"];
target = d.FileDescriptorProto(
    name="mine/t.proto", package="mine", syntax="proto2", dependency=["mine/opts.proto"],
)
target.message_type.add(name="M").field.add(
    name="s", number=1, type=FD.TYPE_STRING, label=FD.LABEL_OPTIONAL,
).options.MergeFromString(bytes.fromhex("8a97220b68656c6c6f20776f726c64"))
fds = d.FileDescriptorSet()
d.DESCRIPTOR.CopyToProto(fds.file.add())
fds.file.extend([options_file("mine", "label", FD.TYPE_STRING), target])

if scenario == "another-type-at-the-number":
    dp.Default().AddSerializedFile(
        options_file("theirs", "meta", FD.TYPE_MESSAGE, ".theirs.Info").SerializeToString()
    )
elif scenario != "nothing":
    raise SystemExit(f"unknown scenario {scenario!r}")

# Two candidates that fit the record equally well, so the ranking reaches the tie-break.
candidates = [Candidate(label, FileDescriptorSetSchema(fds, "mine.M")) for label in ("a", "b")]
try:
    report = match(b"\x0a\x02ok", candidates)
except DecodeError:
    print(json.dumps("DecodeError"))
    raise SystemExit(0)
ranked = [[fit.label, fit.parse_outcome] for fit in report.ranked]
print(json.dumps([report.verdict, report.ambiguous_top, ranked]))
"""

_TIED = ["multiple_clean_matches", True, [["a", "clean"], ["b", "clean"]]]


def test_a_tied_forensics_match_while_the_default_pool_declares_nothing_control() -> None:
    assert _in_a_fresh_interpreter(_TIED_MATCH, "nothing") == _TIED


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=_REPARSE + (
        "Two forensics match candidates built before an unrelated message-typed "
        "extension took one of the schema's option numbers tie, and the tie-break "
        "(_drift.compatibility_score through _descriptors._file_message_index) copies "
        "each file back to a FileDescriptorProto, so DecodeError escapes match() where "
        "it should report multiple_clean_matches. Both backends."
    ),
)
def test_a_tied_forensics_match_completes_whatever_the_default_pool_declares() -> None:
    got = _in_a_fresh_interpreter(_TIED_MATCH, "another-type-at-the-number")
    if got not in (_TIED, "DecodeError"):
        raise RuntimeError(f"neither the defect nor the fix: {got!r}")
    assert got == _TIED, "DecodeError escaped forensics match's tie-break"
