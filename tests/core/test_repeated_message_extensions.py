"""A repeated message-typed extension parses, and reads, under both backends.

Pure-Python keeps a message class on its descriptor and builds it only when
asked. It asks for a declared field's type when it builds the message that
declares the field, and for a singular message-typed extension's type the
first time one is read. Nothing asks for the element type of a *repeated*
message-typed extension, so parsing one raised::

    AttributeError: 'Descriptor' object has no attribute '_concrete_class'

That reached every command that parses a payload (``diff``, ``storage``,
``forensics``) and every read of a custom option, where one such option in an
element's bytes failed the read of every option beside it. upb builds a class
wherever one is asked for and never had the defect, so under upb these tests
pin the answers pure-Python has to match.

The two halves are fixed differently. A payload's class is resolved before
its bytes exist, so ``get_message_class`` walks the schema and builds every
such class the message can reach. An option's bytes are at hand when it is
read, so the reader builds what those bytes hold, and only after pure-Python's
parse has raised.

Every test builds a pool of its own: a class, once built, stays on its
descriptor, and a test that inherited one would pass with the fix removed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner
from google.protobuf import descriptor_pb2, descriptor_pool, message_factory
from google.protobuf.internal import api_implementation
from google.protobuf.message import DecodeError

from protokit import _extensions, _fieldview
from protokit._pools import build_pool, get_message_class
from protokit.message.cli import main as diff_main
from protokit.options import get_option_value
from protokit.storage.schema_source import FileDescriptorSetSchema

FD = descriptor_pb2.FieldDescriptorProto
_OPTIONAL, _REPEATED = FD.LABEL_OPTIONAL, FD.LABEL_REPEATED


def _varint(n: int) -> bytes:
    out = bytearray()
    while n > 0x7F:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    out.append(n)
    return bytes(out)


def _record(number: int, wire_type: int, payload: bytes) -> bytes:
    body = _varint(len(payload)) + payload if wire_type == 2 else payload
    return _varint(number << 3 | wire_type) + body


# ---------------------------------------------------------------------------
# Payloads
# ---------------------------------------------------------------------------


def _payload_set() -> descriptor_pb2.FileDescriptorSet:
    """``rx.Node`` takes a repeated ``rx.Elem``; ``rx.Elem`` a repeated ``rx.Deep``.

    The extensions live in a second file, and the second one inside a message,
    so neither is found by looking at ``Node``'s own file or scope.
    """
    node = descriptor_pb2.FileDescriptorProto(name="rx/node.proto", package="rx", syntax="proto2")
    message = node.message_type.add(name="Node")
    message.field.add(
        name="child", number=1, type=FD.TYPE_MESSAGE, label=_OPTIONAL, type_name=".rx.Node",
    )
    message.extension_range.add(start=100, end=200)
    elem = node.message_type.add(name="Elem")
    elem.field.add(name="id", number=1, type=FD.TYPE_INT32, label=_OPTIONAL)
    elem.extension_range.add(start=100, end=200)
    node.message_type.add(name="Deep").field.add(
        name="n", number=1, type=FD.TYPE_INT32, label=_OPTIONAL,
    )
    # Holds a Node as a declared field and takes no extension itself.
    node.message_type.add(name="Holder").field.add(
        name="node", number=1, type=FD.TYPE_MESSAGE, label=_OPTIONAL, type_name=".rx.Node",
    )

    ext = descriptor_pb2.FileDescriptorProto(
        name="rx/ext.proto", package="rx", syntax="proto2", dependency=["rx/node.proto"],
    )
    ext.extension.add(
        name="items", number=100, type=FD.TYPE_MESSAGE, label=_REPEATED,
        type_name=".rx.Elem", extendee=".rx.Node",
    )
    ext.extension.add(
        name="numbers", number=101, type=FD.TYPE_INT32, label=_REPEATED, extendee=".rx.Node",
    )
    ext.message_type.add(name="Scope").extension.add(
        name="deeper", number=100, type=FD.TYPE_MESSAGE, label=_REPEATED,
        type_name=".rx.Deep", extendee=".rx.Elem",
    )
    return descriptor_pb2.FileDescriptorSet(file=[ext, node])


def _elem(elem_id: int, *deep: int) -> bytes:
    return _record(1, 0, _varint(elem_id)) + b"".join(
        _record(100, 2, _record(1, 0, _varint(n))) for n in deep
    )


def _node(*elems: bytes) -> bytes:
    return b"".join(_record(100, 2, elem) for elem in elems)


def _items(pool: Any, node: Any) -> list[tuple[int, list[int]]]:
    """``[(elem id, [deep n, ...]), ...]`` as ``node`` holds them."""
    items = pool.FindExtensionByName("rx.items")
    deeper = pool.FindExtensionByName("rx.Scope.deeper")
    return [
        (elem.id, [deep.n for deep in elem.Extensions[deeper]]) for elem in node.Extensions[items]
    ]


class TestAPayloadParses:
    """``get_message_class`` hands back a class a payload can be parsed into."""

    def test_at_the_top_of_the_message(self) -> None:
        pool = build_pool(_payload_set())
        node = get_message_class(pool, "rx.Node").FromString(_node(_elem(1), _elem(2)))  # type: ignore[attr-defined]
        assert _items(pool, node) == [(1, []), (2, [])]

    def test_inside_a_declared_field(self) -> None:
        pool = build_pool(_payload_set())
        node = get_message_class(pool, "rx.Node").FromString(_record(1, 2, _node(_elem(3))))  # type: ignore[attr-defined]
        assert _items(pool, node.child) == [(3, [])]

    def test_inside_an_element_of_another_one(self) -> None:
        pool = build_pool(_payload_set())
        node = get_message_class(pool, "rx.Node").FromString(_node(_elem(1, 7, 8)))  # type: ignore[attr-defined]
        assert _items(pool, node) == [(1, [7, 8])]

    def test_on_a_type_the_message_reaches_only_through_a_declared_field(self) -> None:
        pool = build_pool(_payload_set())
        holder = get_message_class(pool, "rx.Holder").FromString(  # type: ignore[attr-defined]
            _record(1, 2, _node(_elem(4, 9))),
        )
        assert _items(pool, holder.node) == [(4, [9])]

    def test_a_storage_schema_resolves_to_a_class_that_parses(self) -> None:
        resolved = FileDescriptorSetSchema(_payload_set(), "rx.Node").resolve()
        node = resolved.message_class.FromString(_node(_elem(5, 6)))  # type: ignore[attr-defined]
        assert _items(resolved.pool, node) == [(5, [6])]


class TestDiffComparesThem:
    @pytest.fixture
    def files(self, tmp_path: Path) -> dict[str, Path]:
        written = {
            "desc": _payload_set().SerializeToString(),
            "one": _node(_elem(1, 7)),
            "two": _node(_elem(2, 7)),
            "nested_one": _record(1, 2, _node(_elem(1))),
            "nested_two": _record(1, 2, _node(_elem(2))),
        }
        paths = {name: tmp_path / f"{name}.bin" for name in written}
        for name, data in written.items():
            paths[name].write_bytes(data)
        return paths

    def _diff(self, files: dict[str, Path], left: str, right: str) -> Any:
        return CliRunner().invoke(
            diff_main,
            [str(files[left]), str(files[right]), "--desc", str(files["desc"]),
             "--message-type", "rx.Node"],
            catch_exceptions=False,
        )

    def test_identical_payloads_are_equal(self, files: dict[str, Path]) -> None:
        result = self._diff(files, "one", "one")
        assert (result.exit_code, "equal" in result.output.lower()) == (0, True)

    @pytest.mark.parametrize(
        ("left", "right", "path"),
        [
            ("one", "two", "(rx.items)[0].id"),
            ("nested_one", "nested_two", "child.(rx.items)[0].id"),
        ],
    )
    def test_a_changed_element_is_reported_at_its_path(
        self, files: dict[str, Path], left: str, right: str, path: str,
    ) -> None:
        result = self._diff(files, left, right)
        assert result.exit_code == 1
        assert f"{path}: 1 → 2" in result.output


# ---------------------------------------------------------------------------
# Custom options
# ---------------------------------------------------------------------------


def _option_set(
    *, through_a_declared_field: bool = False, written_first: bytes = b"",
) -> descriptor_pb2.FileDescriptorSet:
    """A field carrying ``rxo.nums = [1, 2]``, two ``rxo.tags``, then ``rxo.count = 7``.

    ``rxo.tags`` is a repeated ``Tag`` option on fields and on files;
    ``rxo.more`` is a repeated ``Deep`` extension of ``Tag`` itself. With
    ``through_a_declared_field`` the option is instead a singular ``Box`` whose
    declared field holds the ``Tag``.
    """
    opts = descriptor_pb2.FileDescriptorProto(
        name="rxo/opts.proto", package="rxo", syntax="proto2",
        dependency=["google/protobuf/descriptor.proto"],
    )
    tag = opts.message_type.add(name="Tag")
    tag.field.add(name="id", number=1, type=FD.TYPE_INT32, label=_OPTIONAL)
    tag.extension_range.add(start=100, end=200)
    opts.message_type.add(name="Deep").field.add(
        name="n", number=1, type=FD.TYPE_INT32, label=_OPTIONAL,
    )
    opts.message_type.add(name="Box").field.add(
        name="tag", number=1, type=FD.TYPE_MESSAGE, label=_OPTIONAL, type_name=".rxo.Tag",
    )
    for extendee in ("FieldOptions", "FileOptions"):
        scope = opts if extendee == "FieldOptions" else opts.message_type.add(name="OnFiles")
        scope.extension.add(
            name="tags", number=50001, type=FD.TYPE_MESSAGE, label=_REPEATED,
            type_name=".rxo.Tag", extendee=f".google.protobuf.{extendee}",
        )
        scope.extension.add(
            name="count", number=50002, type=FD.TYPE_INT32, label=_OPTIONAL,
            extendee=f".google.protobuf.{extendee}",
        )
    opts.extension.add(
        name="nums", number=50004, type=FD.TYPE_INT32, label=_REPEATED,
        extendee=".google.protobuf.FieldOptions",
    )
    opts.extension.add(
        name="box", number=50003, type=FD.TYPE_MESSAGE, label=_OPTIONAL,
        type_name=".rxo.Box", extendee=".google.protobuf.FieldOptions",
    )
    opts.extension.add(
        name="more", number=100, type=FD.TYPE_MESSAGE, label=_REPEATED,
        type_name=".rxo.Deep", extendee=".rxo.Tag",
    )

    target = descriptor_pb2.FileDescriptorProto(
        name="rxo/t.proto", package="rxo", syntax="proto2", dependency=["rxo/opts.proto"],
    )
    second_tag = _record(1, 0, _varint(2)) + _record(100, 2, _record(1, 0, _varint(9)))
    tags = _record(50001, 2, _record(1, 0, _varint(1))) + _record(50001, 2, second_tag)
    target.options.MergeFromString(tags + _record(50002, 0, _varint(7)))
    field = target.message_type.add(name="M").field.add(
        name="f", number=1, type=FD.TYPE_INT32, label=_OPTIONAL,
    )
    if through_a_declared_field:
        field.options.MergeFromString(_record(50003, 2, _record(1, 2, second_tag)))
    else:
        nums = _record(50004, 0, _varint(1)) + _record(50004, 0, _varint(2))
        field.options.MergeFromString(
            written_first + nums + tags + _record(50002, 0, _varint(7)),
        )
    fds = descriptor_pb2.FileDescriptorSet()
    descriptor_pb2.DESCRIPTOR.CopyToProto(fds.file.add())
    fds.file.extend([opts, target])
    return fds


def _tags(pool: Any, value: Any) -> list[tuple[int, list[int]]]:
    more = pool.FindExtensionByName("rxo.more")
    return [(tag.id, [deep.n for deep in tag.Extensions[more]]) for tag in value]


class TestACustomOptionReads:
    def test_the_repeated_message_option_itself(self) -> None:
        pool = build_pool(_option_set())
        field = pool.FindMessageTypeByName("rxo.M").fields_by_name["f"]
        assert _tags(pool, get_option_value(field, "rxo.tags")) == [(1, []), (2, [9])]

    def test_an_option_beside_it(self) -> None:
        pool = build_pool(_option_set())
        field = pool.FindMessageTypeByName("rxo.M").fields_by_name["f"]
        assert get_option_value(field, "rxo.count") == 7

    def test_an_option_written_before_it_is_read_once(self) -> None:
        # Pure-Python's first parse has stored these two by the time it raises.
        pool = build_pool(_option_set())
        field = pool.FindMessageTypeByName("rxo.M").fields_by_name["f"]
        assert list(get_option_value(field, "rxo.nums")) == [1, 2]  # type: ignore[call-overload]

    def test_after_an_option_that_does_not_parse(self) -> None:
        # ``box`` claims five bytes for its tag and holds two. The whole read
        # fails on it before reaching the tags, so they are read on their own,
        # by a second parse that meets the unbuilt class first.
        malformed = _record(50003, 2, b"\x0a\x05ab")
        pool = build_pool(_option_set(written_first=malformed))
        field = pool.FindMessageTypeByName("rxo.M").fields_by_name["f"]
        assert _tags(pool, get_option_value(field, "rxo.tags")) == [(1, []), (2, [9])]
        with pytest.raises(DecodeError, match="rxo.box"):
            get_option_value(field, "rxo.box")

    def test_one_an_option_reaches_only_through_a_declared_field(self) -> None:
        pool = build_pool(_option_set(through_a_declared_field=True))
        field = pool.FindMessageTypeByName("rxo.M").fields_by_name["f"]
        box = get_option_value(field, "rxo.box")
        assert _tags(pool, [box.tag]) == [(2, [9])]  # type: ignore[attr-defined]

    def test_on_a_file(self) -> None:
        # The shape of ``(google.api.resource_definition)``.
        pool = build_pool(_option_set())
        file = pool.FindFileByName("rxo/t.proto")
        assert get_option_value(file, "rxo.OnFiles.count") == 7
        assert _tags(pool, get_option_value(file, "rxo.OnFiles.tags")) == [(1, []), (2, [9])]

    def test_a_custom_lint_rule_reads_the_option_beside_it(self, tmp_path: Path) -> None:
        from protokit.schema.lint._cli_utils import _load_descriptor_sets_to_result
        from protokit.schema.lint._config import CustomAnnotationRuleSpec
        from protokit.schema.lint._custom_rules import build_synthetic_module, synthetic_rule_ids
        from protokit.schema.lint.engine import LintEngine
        from protokit.schema.lint.model import ElementKind, LintProfile, LintSeverity

        path = tmp_path / "set.binpb"
        path.write_bytes(_option_set().SerializeToString())
        # 7 is not allowed, so a finding carrying it proves the rule read the option.
        spec = CustomAnnotationRuleSpec(
            rule_suffix="count", option="rxo.count",
            element_kinds=(ElementKind.FIELD,), allowed_values=(1,),
        )
        engine = LintEngine()
        engine.load_rule_pack(build_synthetic_module([spec], LintEngine()))
        profile = LintProfile(
            name="_t", rule_ids=synthetic_rule_ids([spec]), min_severity=LintSeverity.INFO,
        )
        report = engine.run(_load_descriptor_sets_to_result((path,)), profile=profile)
        assert [w.category for w in report.runtime_warnings] == []
        assert [
            x.params.get("actual_value") for x in report.findings
            if x.violation_kind == "custom-annotation-value-mismatch"
        ] == ["7"]


# ---------------------------------------------------------------------------
# What gets built, and when
# ---------------------------------------------------------------------------


def _unbuilt(pool: Any, *names: str) -> list[str]:
    """Which of ``names`` have no class on their descriptor yet."""
    return [
        name for name in names
        if not hasattr(pool.FindMessageTypeByName(name), "_concrete_class")
    ]


class TestThePayloadWalk:
    def test_nothing_is_built_before_it(self) -> None:
        # The premise of every test in this file, on both backends.
        pool = build_pool(_payload_set())
        assert _unbuilt(pool, "rx.Elem", "rx.Deep") == ["rx.Elem", "rx.Deep"]

    def test_it_builds_each_element_type_the_message_reaches(self) -> None:
        pool = build_pool(_payload_set())
        _fieldview.build_extension_classes(pool.FindMessageTypeByName("rx.Holder"))
        assert _unbuilt(pool, "rx.Elem", "rx.Deep") == []

    def test_a_pool_built_by_hand_is_walked_too(self) -> None:
        pool = descriptor_pool.DescriptorPool()
        for file in reversed(_payload_set().file):
            pool.Add(file)
            pool.FindFileByName(file.name)
        node = get_message_class(pool, "rx.Node").FromString(_node(_elem(1, 2)))  # type: ignore[attr-defined]
        assert _items(pool, node) == [(1, [2])]


class TestTheOptionReaderBuildsWhatTheBytesHold:
    """``_extensions._build_element_classes``, which only pure-Python's parse failure calls."""

    @staticmethod
    def _field_options(pool: Any) -> Any:
        return pool.FindMessageTypeByName("google.protobuf.FieldOptions")

    def test_each_repeated_message_extension_at_any_depth(self) -> None:
        pool = build_pool(_option_set())
        second = _record(1, 0, _varint(2)) + _record(100, 2, _record(1, 0, _varint(9)))
        data = _record(50001, 2, second) + _record(50002, 0, _varint(7))
        assert _extensions._build_element_classes(self._field_options(pool), data) is True
        assert _unbuilt(pool, "rxo.Tag", "rxo.Deep") == []
        # Nothing is left, which is what lets a second failure propagate.
        assert _extensions._build_element_classes(self._field_options(pool), data) is False

    def test_nothing_the_bytes_do_not_hold(self) -> None:
        pool = build_pool(_option_set())
        data = _record(50001, 2, _record(1, 0, _varint(1))) + _record(50002, 0, _varint(7))
        assert _extensions._build_element_classes(self._field_options(pool), data) is True
        assert _unbuilt(pool, "rxo.Tag", "rxo.Deep") == ["rxo.Deep"]

    @pytest.mark.parametrize("number", [1, 100, 70000])
    def test_a_records_body_is_what_lies_inside_it(self, number: int) -> None:
        inside = _record(1, 0, _varint(9))
        group = _varint(number << 3 | 3) + inside + _varint(number << 3 | 4)
        assert _extensions._body(group) == inside
        assert _extensions._body(_record(number, 2, inside)) == inside
        assert _extensions._body(_record(number, 0, _varint(9))) is None

    @pytest.mark.parametrize(
        "data",
        [
            b"",
            _record(50002, 0, _varint(7)),            # a scalar option
            _record(50001, 0, _varint(7)),            # the message option's number, as a varint
            _record(60000, 2, b"\x08\x01"),           # a number nothing declares
            _record(50001, 2, b"\xff"),               # an element that is not a message
            b"\x0a",                                  # a truncated record
        ],
    )
    def test_bytes_with_nothing_to_build_build_nothing_and_do_not_raise(self, data: bytes) -> None:
        pool = build_pool(_option_set())
        built = _extensions._build_element_classes(self._field_options(pool), data)
        # The message option's own class is the one thing a well-formed prefix can ask for.
        assert built is (data == _record(50001, 2, b"\xff"))
        assert "rxo.Deep" in _unbuilt(pool, "rxo.Tag", "rxo.Deep")


class TestAnAttributeErrorThatIsNotThisOne:
    def test_it_propagates_and_the_parse_is_not_repeated(self) -> None:
        pool = build_pool(_option_set())

        class Broken:
            DESCRIPTOR = pool.FindMessageTypeByName("google.protobuf.FieldOptions")
            parses = 0

            def MergeFromString(self, data: bytes) -> None:  # noqa: N802
                self.parses += 1
                raise AttributeError("something else")

        broken = Broken()
        with pytest.raises(AttributeError, match="something else"):
            _extensions._merge(broken, _record(50002, 0, _varint(7)))
        assert broken.parses == 1

    def test_one_that_survives_the_build_propagates_from_the_second_parse(self) -> None:
        pool = build_pool(_option_set())

        class Broken:
            DESCRIPTOR = pool.FindMessageTypeByName("google.protobuf.FieldOptions")
            parses = cleared = 0

            def MergeFromString(self, data: bytes) -> None:  # noqa: N802
                self.parses += 1
                raise AttributeError("still broken")

            def Clear(self) -> None:  # noqa: N802
                self.cleared += 1

        broken = Broken()
        with pytest.raises(AttributeError, match="still broken"):
            _extensions._merge(broken, _record(50001, 2, _record(1, 0, _varint(1))))
        assert (broken.parses, broken.cleared) == (2, 1)

    def test_the_backend_that_needs_the_second_parse_is_pure_python(self) -> None:
        # protobuf 5.27.5. If upb starts raising here, or pure-Python stops,
        # the mutation proofs for ``_merge`` have changed sides.
        pool = build_pool(_option_set())
        options = message_factory.GetMessageClass(
            pool.FindMessageTypeByName("google.protobuf.FieldOptions"),
        )()
        data = _record(50001, 2, _record(1, 0, _varint(1)))
        if api_implementation.Type() == "python":
            with pytest.raises(AttributeError, match="_concrete_class"):
                options.MergeFromString(data)
        else:
            options.MergeFromString(data)
