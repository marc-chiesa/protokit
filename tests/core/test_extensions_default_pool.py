"""A custom option reads the same whatever the default pool declares.

``desc.GetOptions()`` is not the options as the schema's file holds them. upb
builds it by decoding those bytes again through the *default* pool's extension
registry, and when that decode fails it keeps what it had and raises nothing.
So an extension the process happens to have registered there — the schema's own
one, generated and imported, or an unrelated one that uses the same number for
another type — decides what a read of an isolated-pool schema returns:

- the options after a record that does not decode as the default pool's type
  are gone, so they read as absent;
- the record itself keeps only what decoded (``'hello world'`` comes back as
  ``'he'``);
- a record that does decode is written back as the other type (an ``int32``
  ``7`` under a ``bool`` comes back as ``1``).

``protokit._extensions.options_of`` reads the bytes from the file the
descriptor was built from instead. Registering an extension in the default pool
cannot be undone, so each scenario below runs in a fresh interpreter; the tests
that stay in this process only *pretend* the default pool declares something.
"""

from __future__ import annotations

import ast
import functools
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from google.protobuf import descriptor_pb2

from protokit import _extensions
from protokit._extensions import options_of, rebind_options
from protokit._pools import build_pool
from tests._editions import requires_editions

_SRC = Path(_extensions.__file__).parents[1]

# argv: scenario name, scratch directory. Prints one JSON object.
_SCENARIO = r"""
import json
import sys
from pathlib import Path

from google.protobuf import descriptor_pb2 as d, descriptor_pool as dp
from google.protobuf.message import DecodeError

from protokit import _extensions, _pools
from protokit._pools import load_pool_from_bytes
from protokit.message.model import FieldPath
from protokit.options import get_option_value
from protokit.schema import CompatibilityLevel, check_compatibility
from protokit.schema.rules import options_changed
from protokit.schema.lint._cli_utils import _load_descriptor_sets_to_result
from protokit.schema.lint._config import CustomAnnotationRuleSpec
from protokit.schema.lint._custom_rules import build_synthetic_module, synthetic_rule_ids
from protokit.schema.lint.engine import LintEngine
from protokit.schema.lint.model import ElementKind, LintProfile, LintSeverity
from protokit.schema.lint.rules.options import field_behavior

FD = d.FieldDescriptorProto
FIELD_OPTIONS = ".google.protobuf.FieldOptions"
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
            extendee=FIELD_OPTIONS,
        )
        if type_name:
            ext.type_name = type_name
    return f


mine = options_file("mine/opts.proto", "mine", [
    ("label", 70001, FD.TYPE_STRING, None),
    ("info", 70002, FD.TYPE_MESSAGE, ".mine.Info"),
    ("count", 70003, FD.TYPE_INT32, None),
])
behavior = d.FileDescriptorProto(
    name="google/api/field_behavior.proto", package="google.api", syntax="proto3",
    dependency=["google/protobuf/descriptor.proto"],
)
enum = behavior.enum_type.add(name="FieldBehavior")
for number, value_name in enumerate(("FIELD_BEHAVIOR_UNSPECIFIED", "OPTIONAL", "REQUIRED")):
    enum.value.add(name=value_name, number=number)
behavior.extension.add(
    name="field_behavior", number=1052, type=FD.TYPE_ENUM, label=FD.LABEL_REPEATED,
    type_name=".google.api.FieldBehavior", extendee=FIELD_OPTIONS,
)


EDITIONS = _pools._implements_editions()


def changed_field(name):
    return ("mine.E", "g") if "editions" in name or "features" in name else ("mine.M", "f")


def schema(count=7, count_under_editions=1, feature=b"hello world", info=b"\x0a\x05ab"):
    target = d.FileDescriptorProto(
        name="mine/t.proto", package="mine", syntax="proto3",
        dependency=["mine/opts.proto", "google/api/field_behavior.proto"],
    )
    field = target.message_type.add(name="M").field.add(
        name="f", number=1, type=FD.TYPE_INT32, label=FD.LABEL_OPTIONAL,
    )
    field.options.deprecated = True
    # label = "hello world"; info, whose one string claims five bytes and holds
    # two; count; field_behavior = REQUIRED twice (the rule reports the duplicate).
    field.options.MergeFromString(
        record(70001, 2, b"hello world") + record(70002, 2, info)
        + record(70003, 0, varint(count)) + record(1052, 0, varint(2)) + record(1052, 0, varint(2))
    )
    # Under editions a field also declares features, a message with extensions
    # of its own: here one at 9990 holding a string, then count.
    editions = d.FileDescriptorProto(
        name="mine/e.proto", package="mine", syntax="editions", edition=d.EDITION_2023,
        dependency=["mine/opts.proto"],
    )
    editions.message_type.add(name="E").field.add(
        name="g", number=1, type=FD.TYPE_INT32, label=FD.LABEL_OPTIONAL,
    ).options.MergeFromString(
        record(21, 2, record(9990, 2, feature)) + record(70003, 0, varint(count_under_editions))
    )
    fds = d.FileDescriptorSet()
    d.DESCRIPTOR.CopyToProto(fds.file.add())
    # A runtime that does not implement editions is refused the editions file,
    # and everything below that needs it is left out.
    fds.file.extend([mine, behavior, target] + ([editions] if EDITIONS else []))
    return fds.SerializeToString()


path = scratch / "set.binpb"
path.write_bytes(schema())

# Every schema is loaded before the default pool learns anything: afterwards the
# loader itself parses the set through the same registry, and refuses it or
# stores the rewritten value.
result = _load_descriptor_sets_to_result((path,))
# For compat every option is well formed (info.s = "ab").
WELL_FORMED = b"\x0a\x02ab"
earlier = load_pool_from_bytes(schema(info=WELL_FORMED))
later = {
    "the_same_schema": schema(info=WELL_FORMED),
    "a_changed_count": schema(info=WELL_FORMED, count=8),
    "a_changed_count_under_editions": schema(info=WELL_FORMED, count_under_editions=2),
    "changed_features_alone": schema(info=WELL_FORMED, feature=b"goodbye"),
}
later = {
    name: load_pool_from_bytes(data) for name, data in later.items()
    if EDITIONS or changed_field(name)[0] != "mine.E"
}

if scenario == "its-own-extensions":
    dp.Default().AddSerializedFile(mine.SerializeToString())
elif scenario == "another-type-at-the-number":
    dp.Default().AddSerializedFile(options_file("theirs/opts.proto", "theirs", [
        ("meta", 70001, FD.TYPE_MESSAGE, ".theirs.Info"),
    ]).SerializeToString())
elif scenario == "another-scalar-at-the-number":
    dp.Default().AddSerializedFile(options_file("theirs/opts.proto", "theirs", [
        ("flag", 70003, FD.TYPE_BOOL, None),
    ]).SerializeToString())
elif scenario == "an-extension-of-features":
    features = options_file("theirs/features.proto", "theirs", [])
    features.extension.add(
        name="feature", number=9990, type=FD.TYPE_MESSAGE, label=FD.LABEL_OPTIONAL,
        type_name=".theirs.Info", extendee=".google.protobuf.FeatureSet",
    )
    dp.Default().AddSerializedFile(features.SerializeToString())
elif scenario != "nothing":
    raise SystemExit(f"unknown scenario {scenario!r}")
declared = sorted(
    e.full_name for e in dp.Default().FindAllExtensions(d.FieldOptions.DESCRIPTOR)
)

f = result.pool.FindMessageTypeByName("mine.M").fields_by_name["f"]
g = result.pool.FindMessageTypeByName("mine.E").fields_by_name["g"] if EDITIONS else None


def read(option, field=f):
    try:
        value = get_option_value(field, option, pool=result.pool)
    except DecodeError as exc:
        return f"DecodeError: {exc}"
    return value if value is None or isinstance(value, (str, int)) else f"a {type(value).__name__}"


def lint(module, rule_ids):
    engine = LintEngine()
    engine.load_rule_pack(module)
    profile = LintProfile(name="_t", rule_ids=rule_ids, min_severity=LintSeverity.INFO)
    report = engine.run(result, profile=profile)
    return {
        "warnings": [w.category for w in report.runtime_warnings],
        "findings": [[x.violation_kind, dict(x.params)] for x in report.findings],
    }


# 7 is not allowed, so a finding carrying it proves the rule read the option.
spec = CustomAnnotationRuleSpec(
    rule_suffix="count", option="mine.count",
    element_kinds=(ElementKind.FIELD,), allowed_values=(1,),
)
custom = lint(build_synthetic_module([spec], LintEngine()), synthetic_rule_ids([spec]))


def rule(new_pool, message, field_name):
    old, new = (
        pool.FindMessageTypeByName(message).fields_by_name[field_name]
        for pool in (earlier, new_pool)
    )
    return [x.rule_id for x in options_changed(old, new, FieldPath(segments=(field_name,)))]


def compat(new_pool, message):
    # check_compatibility also copies each file back to a FileDescriptorProto,
    # and that copy is parsed through the default pool's registry.
    try:
        report = check_compatibility(
            earlier, message, new_pool, message, level=CompatibilityLevel.STRICT,
        )
    except DecodeError:
        return "DecodeError"
    return [finding.rule_id for finding in report.findings]


behavior_report = lint(field_behavior, frozenset({field_behavior.RULE_ID}))
print(json.dumps({
    "declared": declared,
    "checked": {
        kind: _extensions._default_pool_extends(kind) for kind in ("FieldOptions", "MessageOptions")
    },
    "label": read("mine.label"),
    "count": read("mine.count"),
    "count_under_editions": read("mine.count", g) if EDITIONS else "no editions",
    "info": read("mine.info"),
    "deprecated": f.GetOptions().deprecated,
    "custom_warnings": custom["warnings"],
    # Every other field in the set has no count at all, and is reported as such.
    "custom": [
        [kind, params.get("actual_value")] for kind, params in custom["findings"]
        if kind != "custom-annotation-absent"
    ],
    "custom_absent": sum(kind == "custom-annotation-absent" for kind, _p in custom["findings"]),
    "behavior_warnings": behavior_report["warnings"],
    "behavior": [kind for kind, _params in behavior_report["findings"]],
    "options_changed": {name: rule(pool, *changed_field(name)) for name, pool in later.items()},
    "compat": {name: compat(pool, changed_field(name)[0]) for name, pool in later.items()},
}))
"""

_SCENARIOS = (
    "nothing", "its-own-extensions", "another-type-at-the-number", "another-scalar-at-the-number",
    "an-extension-of-features",
)


def _outcome(scenario: str) -> dict[str, Any]:
    """One scenario's results; skips a scenario that needs editions where there are none."""
    if scenario == "an-extension-of-features":
        requires_editions()
    return _ran(scenario)


@functools.cache
def _ran(scenario: str) -> dict[str, Any]:
    import tempfile

    with tempfile.TemporaryDirectory() as scratch:
        result = subprocess.run(
            [sys.executable, "-c", _SCENARIO, scenario, scratch],
            capture_output=True, text=True, check=False, timeout=300,
            env={**os.environ, "PYTHONPATH": str(_SRC)},
        )
    if result.returncode != 0:
        # Not an assertion: a pin that expects AssertionError must not accept this.
        raise RuntimeError(f"scenario {scenario!r} did not run:\n{result.stderr}")
    outcome: dict[str, Any] = json.loads(result.stdout.strip().splitlines()[-1])
    return outcome


@pytest.mark.parametrize("scenario", _SCENARIOS)
class TestTheDefaultPoolCannotChangeWhatAnOptionReads:
    """One schema, read after the default pool has been given something that overlaps it."""

    def test_the_scenario_registered_what_it_names(self, scenario: str) -> None:
        expected = {
            "nothing": [],
            "its-own-extensions": ["mine.count", "mine.info", "mine.label"],
            "another-type-at-the-number": ["theirs.meta"],
            "another-scalar-at-the-number": ["theirs.flag"],
            "an-extension-of-features": [],
        }
        assert _outcome(scenario)["declared"] == expected[scenario]

    def test_get_option_value_returns_what_the_schema_declares(self, scenario: str) -> None:
        outcome = _outcome(scenario)
        assert (outcome["label"], outcome["count"]) == ("hello world", 7)

    def test_an_option_beside_declared_features_reads(self, scenario: str) -> None:
        requires_editions()
        assert _outcome(scenario)["count_under_editions"] == 1

    def test_the_malformed_option_still_raises_naming_itself(self, scenario: str) -> None:
        assert _outcome(scenario)["info"].startswith("DecodeError: mine.info")

    def test_a_custom_rule_sees_the_option(self, scenario: str) -> None:
        outcome = _outcome(scenario)
        assert outcome["custom_warnings"] == []
        assert outcome["custom"] == [["custom-annotation-value-mismatch", "7"]]

    def test_the_field_behavior_rule_sees_the_option(self, scenario: str) -> None:
        outcome = _outcome(scenario)
        assert outcome["behavior_warnings"] == []
        assert outcome["behavior"] == [f"{field_behavior_rule_id()}/duplicate-value"]

    def test_a_declared_option_field_is_unaffected(self, scenario: str) -> None:
        # upb writes a message's own fields before its extensions, so they are
        # decoded before any record that can fail.
        assert _outcome(scenario)["deprecated"] is True


_LATER_VERSIONS = {
    "the_same_schema": [],
    "a_changed_count": ["options_changed"],
    "a_changed_count_under_editions": ["options_changed"],
    # On protobuf 5.27 ``GetOptions()`` leaves ``features`` out and the file read
    # holds them; the verdict must not depend on which the default pool selected.
    "changed_features_alone": [],
}

# Where the other type cannot decode the option's bytes, ``check_compatibility``
# raises before any rule runs, on both backends: it copies each file back to a
# ``FileDescriptorProto``, which is parsed through the default pool's registry.
# ``tests/core/test_audit_default_pool_reparse_pins.py`` pins each of these.
COMPAT_DOES_NOT_COMPLETE = (
    ("another-type-at-the-number", "the_same_schema"),
    ("another-type-at-the-number", "a_changed_count"),
    ("an-extension-of-features", "a_changed_count_under_editions"),
    ("an-extension-of-features", "changed_features_alone"),
)
_COMPAT_COMPLETES = tuple(
    (scenario, later) for scenario in _SCENARIOS for later in _LATER_VERSIONS
    if (scenario, later) not in COMPAT_DOES_NOT_COMPLETE
)


def _needs_editions(later: str) -> None:
    if later in ("a_changed_count_under_editions", "changed_features_alone"):
        requires_editions()


def compat_outcome(scenario: str, later: str) -> tuple[Any, list[str]]:
    """``(what check_compatibility returned, what it should)`` for one later version."""
    _needs_editions(later)
    return _outcome(scenario)["compat"][later], _LATER_VERSIONS[later]


class TestTheDefaultPoolCannotChangeWhatCompatCompares:
    """One schema against four later versions of it, each loaded before the default pool changed."""

    @pytest.mark.parametrize("scenario", _SCENARIOS)
    @pytest.mark.parametrize("later", _LATER_VERSIONS)
    def test_the_rule_reports_a_changed_option_and_nothing_else(
        self, scenario: str, later: str
    ) -> None:
        _needs_editions(later)
        assert _outcome(scenario)["options_changed"][later] == _LATER_VERSIONS[later]

    @pytest.mark.parametrize(("scenario", "later"), _COMPAT_COMPLETES)
    def test_check_compatibility_agrees_wherever_it_completes(
        self, scenario: str, later: str
    ) -> None:
        got, expected = compat_outcome(scenario, later)
        assert got == expected


def field_behavior_rule_id() -> str:
    from protokit.schema.lint.rules.options.field_behavior import RULE_ID

    return RULE_ID


# ---------------------------------------------------------------------------
# In this process: every kind of descriptor is found in its file.
# ---------------------------------------------------------------------------

FD = descriptor_pb2.FieldDescriptorProto
_PKG = "pkoptfile"
# (extension name, options message it extends, number)
_KINDS: tuple[tuple[str, str, int], ...] = (
    ("file_opt", "FileOptions", 68501),
    ("msg_opt", "MessageOptions", 68502),
    ("field_opt", "FieldOptions", 68503),
    ("oneof_opt", "OneofOptions", 68504),
    ("enum_opt", "EnumOptions", 68505),
    ("value_opt", "EnumValueOptions", 68506),
    ("svc_opt", "ServiceOptions", 68507),
    ("method_opt", "MethodOptions", 68508),
)
_NUMBER = {extendee: number for _name, extendee, number in _KINDS}
_NAME = {extendee: name for name, extendee, _number in _KINDS}


def _varint(value: int) -> bytes:
    out = bytearray()
    while value > 0x7F:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    out.append(value)
    return bytes(out)


class _Fixture:
    """A file with an option on one descriptor of every shape, each a distinct value."""

    def __init__(self) -> None:
        self.expected: dict[str, int] = {}
        self._next = 100
        descriptor_file = descriptor_pb2.FileDescriptorProto()
        descriptor_pb2.DESCRIPTOR.CopyToProto(descriptor_file)
        ext_file = descriptor_pb2.FileDescriptorProto(
            name="pkoptfile_ext.proto", package=_PKG, syntax="proto2",
            dependency=["google/protobuf/descriptor.proto"],
        )
        for name, extendee, number in _KINDS:
            ext_file.extension.add(
                name=name, number=number, type=FD.TYPE_INT32, label=FD.LABEL_OPTIONAL,
                extendee=f".google.protobuf.{extendee}",
            )
        f = descriptor_pb2.FileDescriptorProto(
            name="pkoptfile_t.proto", package=_PKG, syntax="proto2",
            dependency=["pkoptfile_ext.proto"],
        )
        self._set("file", f.options, "FileOptions")

        outer = f.message_type.add(name="Outer")
        self._set("message", outer.options, "MessageOptions")
        outer.extension_range.add(start=100, end=200)
        self._set("field", self._field(outer, "plain", 1).options, "FieldOptions")
        self._set("oneof", outer.oneof_decl.add(name="choice").options, "OneofOptions")
        member = self._field(outer, "in_oneof", 2)
        member.oneof_index = 0
        self._set("oneof member", member.options, "FieldOptions")
        entry = outer.nested_type.add(name="ByKeyEntry")
        entry.options.map_entry = True
        self._field(entry, "key", 1)
        self._field(entry, "value", 2)
        by_key = outer.field.add(
            name="by_key", number=3, type=FD.TYPE_MESSAGE, label=FD.LABEL_REPEATED,
            type_name=f".{_PKG}.Outer.ByKeyEntry",
        )
        self._set("map field", by_key.options, "FieldOptions")

        inner = outer.nested_type.add(name="Inner")
        self._set("nested message", inner.options, "MessageOptions")
        self._set("nested field", self._field(inner, "plain", 1).options, "FieldOptions")
        deepest = inner.nested_type.add(name="Deepest")
        self._set("twice-nested message", deepest.options, "MessageOptions")
        nested_enum = inner.enum_type.add(name="Shade")
        self._set("nested enum", nested_enum.options, "EnumOptions")
        self._set(
            "nested enum value", nested_enum.value.add(name="DARK", number=0).options,
            "EnumValueOptions",
        )
        # An extension is found by its position among those of its own scope,
        # so each scope declares another one first.
        inner.extension.add(
            name="scoped_first", number=102, type=FD.TYPE_INT32, label=FD.LABEL_OPTIONAL,
            extendee=f".{_PKG}.Outer",
        )
        scoped = inner.extension.add(
            name="scoped_ext", number=101, type=FD.TYPE_INT32, label=FD.LABEL_OPTIONAL,
            extendee=f".{_PKG}.Outer",
        )
        self._set("message-scoped extension", scoped.options, "FieldOptions")

        top_enum = f.enum_type.add(name="Colour")
        top_enum.options.allow_alias = True
        self._set("enum", top_enum.options, "EnumOptions")
        self._set(
            "enum value", top_enum.value.add(name="RED", number=0).options, "EnumValueOptions",
        )
        self._set(
            "enum value alias", top_enum.value.add(name="CRIMSON", number=0).options,
            "EnumValueOptions",
        )
        f.extension.add(
            name="top_first", number=103, type=FD.TYPE_INT32, label=FD.LABEL_OPTIONAL,
            extendee=f".{_PKG}.Outer",
        )
        top_ext = f.extension.add(
            name="top_ext", number=100, type=FD.TYPE_INT32, label=FD.LABEL_OPTIONAL,
            extendee=f".{_PKG}.Outer",
        )
        self._set("file-scoped extension", top_ext.options, "FieldOptions")

        svc = f.service.add(name="Svc")
        self._set("service", svc.options, "ServiceOptions")
        method = svc.method.add(
            name="Call", input_type=f".{_PKG}.Outer", output_type=f".{_PKG}.Outer",
        )
        self._set("method", method.options, "MethodOptions")
        # Both backends build a service that declares one method name twice.
        again = svc.method.add(
            name="Call", input_type=f".{_PKG}.Outer", output_type=f".{_PKG}.Outer",
        )
        self._set("second method of one name", again.options, "MethodOptions")
        # The same simple names again, in another scope: a lookup by bare name
        # that ignored the scope would land on these.
        other = f.message_type.add(name="Inner")
        self._set("top-level message of a nested one's name", other.options, "MessageOptions")
        self._set(
            "field of that message", self._field(other, "plain", 1).options, "FieldOptions",
        )

        fds = descriptor_pb2.FileDescriptorSet()
        fds.file.extend([descriptor_file, ext_file, f])
        self.pool = build_pool(fds)

    @staticmethod
    def _field(message: Any, name: str, number: int) -> Any:
        return message.field.add(
            name=name, number=number, type=FD.TYPE_INT32, label=FD.LABEL_OPTIONAL,
        )

    def _set(self, label: str, options: Any, options_type: str) -> None:
        self._next += 1
        options.MergeFromString(_varint(_NUMBER[options_type] << 3) + _varint(self._next))
        self.expected[label] = self._next

    def descriptor(self, label: str) -> Any:
        pool = self.pool
        outer = pool.FindMessageTypeByName(f"{_PKG}.Outer")
        inner = outer.nested_types_by_name["Inner"]
        other = pool.FindMessageTypeByName(f"{_PKG}.Inner")
        colour = pool.FindEnumTypeByName(f"{_PKG}.Colour")
        shade = inner.enum_types_by_name["Shade"]
        return {
            "file": lambda: pool.FindFileByName("pkoptfile_t.proto"),
            "message": lambda: outer,
            "field": lambda: outer.fields_by_name["plain"],
            "oneof": lambda: outer.oneofs_by_name["choice"],
            "oneof member": lambda: outer.fields_by_name["in_oneof"],
            "map field": lambda: outer.fields_by_name["by_key"],
            "nested message": lambda: inner,
            "nested field": lambda: inner.fields_by_name["plain"],
            "twice-nested message": lambda: inner.nested_types_by_name["Deepest"],
            "nested enum": lambda: shade,
            "nested enum value": lambda: shade.values_by_name["DARK"],
            "message-scoped extension": lambda: inner.extensions_by_name["scoped_ext"],
            "enum": lambda: colour,
            "enum value": lambda: colour.values_by_name["RED"],
            "enum value alias": lambda: colour.values_by_name["CRIMSON"],
            "file-scoped extension": lambda: pool.FindExtensionByName(f"{_PKG}.top_ext"),
            "service": lambda: pool.FindServiceByName(f"{_PKG}.Svc"),
            "method": lambda: pool.FindServiceByName(f"{_PKG}.Svc").methods[0],
            "second method of one name": lambda: pool.FindServiceByName(f"{_PKG}.Svc").methods[1],
            "top-level message of a nested one's name": lambda: other,
            "field of that message": lambda: other.fields_by_name["plain"],
        }[label]()


_FIXTURE = _Fixture()


@pytest.fixture
def default_pool_declares_something(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_extensions, "_default_pool_extends", lambda options_type: True)


@pytest.mark.parametrize("label", sorted(_FIXTURE.expected))
class TestEveryDescriptorIsFoundInItsFile:
    def test_its_option_reads_from_the_file(
        self, label: str, default_pool_declares_something: None,
    ) -> None:
        desc = _FIXTURE.descriptor(label)
        options = options_of(desc)
        # Not the object GetOptions() hands out: the file's own copy.
        assert type(options) is not type(desc.GetOptions())
        ext = _FIXTURE.pool.FindExtensionByName(f"{_PKG}.{_NAME[options.DESCRIPTOR.name]}")
        assert rebind_options(options, ext).Extensions[ext] == _FIXTURE.expected[label]

    def test_the_file_holds_what_get_options_returns(
        self, label: str, default_pool_declares_something: None,
    ) -> None:
        desc = _FIXTURE.descriptor(label)
        assert options_of(desc).SerializeToString() == desc.GetOptions().SerializeToString()

    def test_get_options_is_returned_while_the_default_pool_declares_nothing(
        self, label: str, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(_extensions, "_default_pool_extends", lambda options_type: False)
        desc = _FIXTURE.descriptor(label)
        assert options_of(desc) is desc.GetOptions()


class TestTwoFieldsOfOneName:
    """Pure-Python builds such a message; upb refuses the file. Neither may read the wrong field."""

    @staticmethod
    def _set() -> descriptor_pb2.FileDescriptorSet:
        f = descriptor_pb2.FileDescriptorProto(name="pkoptfile_dup.proto", syntax="proto2")
        message = f.message_type.add(name="Twice")
        for number, deprecated in ((1, True), (2, False)):
            message.field.add(
                name="f", number=number, type=FD.TYPE_INT32, label=FD.LABEL_OPTIONAL,
            ).options.deprecated = deprecated
        return descriptor_pb2.FileDescriptorSet(file=[f])

    def test_each_reads_its_own_options(self, default_pool_declares_something: None) -> None:
        from google.protobuf.internal import api_implementation

        from protokit._pools import DescriptorPoolError

        if api_implementation.Type() != "python":
            with pytest.raises(DescriptorPoolError):
                build_pool(self._set())
            return
        fields = build_pool(self._set()).FindMessageTypeByName("Twice").fields
        assert [options_of(field).deprecated for field in fields] == [True, False]


class TestTwoMessagesOfOneName:
    """Pure-Python builds such a file; upb refuses it. A message carries no index to find it by."""

    @staticmethod
    def _pool(first_field: str, *, first_deprecated: bool) -> Any:
        from google.protobuf import descriptor_pool

        f = descriptor_pb2.FileDescriptorProto(name="pkoptfile_twins.proto", syntax="proto2")
        f.message_type.add(name="Twin").field.add(
            name=first_field, number=1, type=FD.TYPE_INT32, label=FD.LABEL_OPTIONAL,
        ).options.deprecated = first_deprecated
        f.message_type.add(name="Twin").field.add(
            name="f", number=1, type=FD.TYPE_INT32, label=FD.LABEL_OPTIONAL,
        )
        pool = descriptor_pool.DescriptorPool()
        pool.AddSerializedFile(f.SerializeToString())
        return pool

    @pytest.mark.parametrize("first_field", ["f", "g"])
    def test_the_file_read_gives_way_to_get_options(
        self, first_field: str, default_pool_declares_something: None,
    ) -> None:
        from google.protobuf.internal import api_implementation

        if api_implementation.Type() != "python":
            with pytest.raises(TypeError, match="duplicate symbol"):
                self._pool(first_field, first_deprecated=True)
            return
        # The pool resolves the name to the second declaration, whose field has
        # no options. Read by name, the file would answer for the first: its
        # deprecated ``f``, or a ``g`` where the descriptor says ``f``.
        pool = self._pool(first_field, first_deprecated=True)
        field = pool.FindMessageTypeByName("Twin").fields[0]
        assert options_of(field) is field.GetOptions()
        assert options_of(field.containing_type) is field.containing_type.GetOptions()
        assert options_of(field).deprecated is False

    def test_the_rule_agrees_with_what_it_said_before_the_default_pool_changed(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from google.protobuf.internal import api_implementation

        from protokit.message.model import FieldPath
        from protokit.schema.rules import options_changed

        if api_implementation.Type() != "python":
            pytest.skip("upb refuses a file that declares one message name twice")
        old, new = (
            self._pool("f", first_deprecated=deprecated).FindMessageTypeByName("Twin").fields[0]
            for deprecated in (False, True)
        )
        path = FieldPath(segments=("f",))
        monkeypatch.setattr(_extensions, "_default_pool_extends", lambda options_type: False)
        before = options_changed(old, new, path)
        monkeypatch.setattr(_extensions, "_default_pool_extends", lambda options_type: True)
        assert options_changed(old, new, path) == before == []


class TestAnEnumDeclaredTwice:
    def test_the_file_read_gives_way_to_get_options(
        self, default_pool_declares_something: None,
    ) -> None:
        from google.protobuf import descriptor_pool
        from google.protobuf.internal import api_implementation

        f = descriptor_pb2.FileDescriptorProto(name="pkoptfile_enum_twins.proto", syntax="proto2")
        for deprecated in (True, False):
            enum = f.enum_type.add(name="Twin")
            enum.value.add(name=f"TWIN_{'A' if deprecated else 'B'}", number=0)
            enum.options.deprecated = deprecated
        pool = descriptor_pool.DescriptorPool()
        if api_implementation.Type() != "python":
            with pytest.raises(TypeError, match="duplicate symbol"):
                pool.AddSerializedFile(f.SerializeToString())
            return
        pool.AddSerializedFile(f.SerializeToString())
        enum_desc = pool.FindEnumTypeByName("Twin")
        assert options_of(enum_desc) is enum_desc.GetOptions()
        assert options_of(enum_desc.values[0]) is enum_desc.values[0].GetOptions()


class TestOptionBytesHoldFeaturesOnlyWhereGetOptionsHasThem:
    """protobuf 5.27 leaves ``features`` out of ``GetOptions()``; 4.25 keeps them there."""

    @staticmethod
    def _field(live: descriptor_pb2.FieldOptions) -> Any:
        from types import SimpleNamespace

        return SimpleNamespace(GetOptions=lambda: live)

    @staticmethod
    def _options(*, features: bool) -> descriptor_pb2.FieldOptions:
        options = descriptor_pb2.FieldOptions(deprecated=True)
        if features:
            options.features.SetInParent()
        return options

    @pytest.mark.parametrize(
        ("live_has_them", "expected"), [(False, False), (True, True)],
    )
    def test_the_file_read_keeps_them_only_if_get_options_did(
        self, live_has_them: bool, expected: bool, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from protokit.schema import rules

        from_the_file = self._options(features=True)
        monkeypatch.setattr(_extensions, "options_of", lambda fd: from_the_file)
        data = rules._option_bytes(self._field(self._options(features=live_has_them)))
        assert descriptor_pb2.FieldOptions.FromString(data).HasField("features") is expected
        assert descriptor_pb2.FieldOptions.FromString(data).deprecated is True
        assert from_the_file.HasField("features")  # the shared message is not modified

    def test_get_options_itself_is_serialized_as_it_is(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from protokit.schema import rules

        live = self._options(features=True)
        monkeypatch.setattr(_extensions, "options_of", lambda fd: fd.GetOptions())
        assert rules._option_bytes(self._field(live)) == live.SerializeToString()


class TestAFileTooDeepForTheStackThatIsLeft:
    """Pure-Python parses a file one stack frame per nested message, and can run out here."""

    def test_get_options_is_returned(
        self, default_pool_declares_something: None, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def too_deep(file_desc: object) -> object:
            raise RecursionError("maximum recursion depth exceeded")

        monkeypatch.setattr(_extensions, "_file_proto", too_deep)
        desc = _FIXTURE.descriptor("nested field")
        assert options_of(desc) is desc.GetOptions()


class TestADescriptorWithNoFile:
    def test_get_options_is_all_there_is(self, default_pool_declares_something: None) -> None:
        from types import SimpleNamespace

        options = descriptor_pb2.FieldOptions(deprecated=True)
        desc = SimpleNamespace(GetOptions=lambda: options, file=None)
        assert options_of(desc) is options


class TestTheDefaultPoolCheck:
    @pytest.mark.parametrize("extendee", [extendee for _name, extendee, _number in _KINDS])
    def test_features_is_the_only_other_message_an_options_message_extends_through(
        self, extendee: str,
    ) -> None:
        # The check asks the default pool about the options message and about
        # FeatureSet. This walks descriptor.proto to say those are all there is.
        seen: dict[str, Any] = {}
        stack = [getattr(descriptor_pb2, extendee).DESCRIPTOR]
        while stack:
            current = stack.pop()
            if current.full_name not in seen:
                seen[current.full_name] = current
                stack.extend(f.message_type for f in current.fields if f.message_type is not None)
        extendable = {name for name, found in seen.items() if found.is_extendable}
        assert extendable == {f"google.protobuf.{extendee}", "google.protobuf.FeatureSet"}

    @pytest.mark.parametrize(
        ("scenario", "expected"),
        [
            ("nothing", {"FieldOptions": False, "MessageOptions": False}),
            ("its-own-extensions", {"FieldOptions": True, "MessageOptions": False}),
            ("an-extension-of-features", {"FieldOptions": True, "MessageOptions": True}),
        ],
    )
    def test_it_answers_for_the_options_message_asked_about(
        self, scenario: str, expected: dict[str, bool],
    ) -> None:
        assert _outcome(scenario)["checked"] == expected


class TestNoReaderBypassesTheFile:
    """Every ``rebind_options`` caller passes ``options_of(desc)``, never ``desc.GetOptions()``."""

    def test_every_caller_reads_through_options_of(self) -> None:
        offenders: list[str] = []
        callers = 0
        for path in sorted(_SRC.rglob("*.py")):
            if path == Path(_extensions.__file__):
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            from_options_of = {
                target.id
                for node in ast.walk(tree) if isinstance(node, ast.Assign)
                for target in node.targets
                if isinstance(target, ast.Name) and _calls(node.value, "options_of")
            }
            for node in ast.walk(tree):
                if not _calls(node, "rebind_options"):
                    continue
                callers += 1
                first = node.args[0]  # type: ignore[attr-defined]
                through = _calls(first, "options_of") or (
                    isinstance(first, ast.Name) and first.id in from_options_of
                )
                if not through:
                    offenders.append(f"{path.relative_to(_SRC)}:{node.lineno}")  # type: ignore[attr-defined]
        assert offenders == []
        assert callers == 3


def _calls(node: ast.AST, name: str) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    return (isinstance(func, ast.Name) and func.id == name) or (
        isinstance(func, ast.Attribute) and func.attr == name
    )
