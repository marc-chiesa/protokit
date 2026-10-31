"""Every path the differ writes parses back through ``FieldPath.parse``.

The differ writes paths in two places: each ``Difference.path`` and each
``Diagnostic.path`` string. ``DiffResult.filter`` and ``protokit diff
--filter`` read the diagnostic strings back with ``FieldPath.parse``, so a
bracket the grammar cannot read turns a filter over the differ's own output
into a usage error. The grammar (``model.py``) and the writer of bracket text
(``_descriptors.format_key``) therefore have to agree on every key type a path
can carry: map keys (integers, booleans, strings) and ``treat_as_map`` keys,
which can also be floats, NaN and infinities, bytes and enum numbers.

A field name outside the identifier grammar only exists in a hand-built
descriptor set, and only pure-Python builds one (upb refuses the name when the
file is added). The differ writes such a name as it is, so the path cannot
parse; ``DiffResult.filter`` then matches it by its string prefix instead of
failing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner
from google.protobuf import descriptor_pb2, descriptor_pool, message_factory, text_format
from google.protobuf.internal import api_implementation
from google.protobuf.message import Message

from protokit.message import DiffResult, MessageDifferencer
from protokit.message.cli import main
from protokit.message.model import FieldHookContext, FieldPath

#: One element type per ``treat_as_map`` key type, each ``{k, v}``.
_KEY_TYPES = {
    "i64": "TYPE_INT64",
    "u64": "TYPE_UINT64",
    "flag": "TYPE_BOOL",
    "text": "TYPE_STRING",
    "f32": "TYPE_FLOAT",
    "f64": "TYPE_DOUBLE",
    "raw": "TYPE_BYTES",
    "shade": "TYPE_ENUM",
}

#: Keys per element type: each is present on both sides with a changed value,
#: except that the last is only on the left and the first only on the right.
_KEYS: dict[str, list[object]] = {
    "i64": [-(2**63), -1, 0, 2**63 - 1],
    "u64": [0, 2**64 - 1],
    "flag": [False, True],
    "text": ["plain", 'quote"', "back\\slash", "close]", "line\nbreak", "esc\x1b[2K", "\r", ""],
    "f32": [1.5, float("inf"), float("-inf"), -0.0],
    "f64": [0.1, 1e-300, 1.7976931348623157e308, float("inf"), -2.5],
    "raw": [b"", b"\x00\xff", b'q"', b"b\\", b"]", b"\n\x1b"],
    "shade": [-1, 0, 2],
}


def _element(name: str, key_type: str) -> str:
    type_name = ' type_name: ".rt.Shade"' if key_type == "TYPE_ENUM" else ""
    return f"""message_type {{ name: "{name}"
      field {{ name: "k" number: 1 type: {key_type} label: LABEL_OPTIONAL{type_name} }}
      field {{ name: "v" number: 2 type: TYPE_STRING label: LABEL_OPTIONAL }} }}"""


def _map_entry(name: str, key_type: str) -> str:
    return f"""nested_type {{ name: "{name}"
        field {{ name: "key" number: 1 type: {key_type} label: LABEL_OPTIONAL }}
        field {{ name: "value" number: 2 type: TYPE_STRING label: LABEL_OPTIONAL }}
        options {{ map_entry: true }} }}"""


_MAPS = {
    "labels": "TYPE_STRING",
    "by_i64": "TYPE_INT64",
    "by_u64": "TYPE_UINT64",
    "by_flag": "TYPE_BOOL",
}


def _file() -> descriptor_pb2.FileDescriptorProto:
    elements = "\n".join(
        _element(f"E_{name}", key_type) for name, key_type in _KEY_TYPES.items()
    )
    repeated = "\n".join(
        f'field {{ name: "{name}_items" number: {n} type: TYPE_MESSAGE '
        f'type_name: ".rt.E_{name}" label: LABEL_REPEATED }}'
        for n, name in enumerate(_KEY_TYPES, start=1)
    )
    maps = "\n".join(
        f'field {{ name: "{name}" number: {n} type: TYPE_MESSAGE '
        f'type_name: ".rt.Root.{name.title().replace("_", "")}Entry" label: LABEL_REPEATED }}\n'
        + _map_entry(f'{name.title().replace("_", "")}Entry', key_type)
        for n, (name, key_type) in enumerate(_MAPS.items(), start=50)
    )
    text = f"""name: "rt.proto" package: "rt" syntax: "proto2"
    enum_type {{ name: "Shade"
      value {{ name: "NEG" number: -1 }} value {{ name: "ZERO" number: 0 }}
      value {{ name: "TWO" number: 2 }} }}
    {elements}
    message_type {{ name: "Root"
      {repeated}
      {maps} }}"""
    return text_format.Parse(text, descriptor_pb2.FileDescriptorProto())


def _root_class() -> type[Message]:
    pool = descriptor_pool.DescriptorPool()
    pool.Add(_file())
    return message_factory.GetMessageClass(pool.FindMessageTypeByName("rt.Root"))


def _pair() -> tuple[Message, Message]:
    """Two ``Root`` messages that differ under every key of every key type."""
    cls = _root_class()
    left, right = cls(), cls()
    for name, keys in _KEYS.items():
        for i, key in enumerate(keys):
            if i != 0:  # the first key is only on the right
                getattr(left, f"{name}_items").add(k=key, v="a")
            if i != len(keys) - 1:  # the last key is only on the left
                getattr(right, f"{name}_items").add(k=key, v="b")
    for name, keys in {
        "labels": _KEYS["text"], "by_i64": _KEYS["i64"],
        "by_u64": _KEYS["u64"], "by_flag": _KEYS["flag"],
    }.items():
        for i, key in enumerate(keys):
            if i != 0:
                getattr(left, name)[key] = "a"
            if i != len(keys) - 1:
                getattr(right, name)[key] = "b"
    return left, right


def _warn_everywhere(ctx: FieldHookContext) -> None:
    ctx.warn("seen")


def _keyed_result() -> DiffResult:
    left, right = _pair()
    d = MessageDifferencer()
    for name in _KEY_TYPES:
        d.treat_as_map(f"{name}_items", key="k")
    d.register_validate_hook(_warn_everywhere)
    return d.compare(left, right)


class TestEveryEmittedPathParsesBack:
    """R2: each ``Difference`` and ``Diagnostic`` path round-trips through ``parse``."""

    def test_every_key_type_is_reached(self) -> None:
        """Control: the run reports under every key type, so the checks below see each one."""
        result = _keyed_result()
        reached = {str(diff.path).split("[", 1)[0] for diff in result}

        assert reached == {f"{name}_items" for name in _KEY_TYPES} | set(_MAPS)
        assert result.diagnostics

    def test_difference_paths_round_trip(self) -> None:
        for diff in _keyed_result():
            text = str(diff.path)
            assert FieldPath.parse(text) == diff.path, text
            assert str(FieldPath.parse(text)) == text

    def test_diagnostic_paths_round_trip(self) -> None:
        for diagnostic in _keyed_result().diagnostics:
            assert diagnostic.path is not None
            assert str(FieldPath.parse(diagnostic.path)) == diagnostic.path

    def test_every_path_is_one_printable_line(self) -> None:
        """A key's control characters are escaped, so each path prints as one line."""
        result = _keyed_result()
        texts = [str(diff.path) for diff in result]
        texts += [diagnostic.path or "" for diagnostic in result.diagnostics]

        bad = [text for text in texts if not text.isprintable()]
        assert bad == []

    def test_filter_over_the_differ_output_keeps_every_difference(self) -> None:
        """``filter`` re-parses every diagnostic path; none of them may raise."""
        result = _keyed_result()

        for name in _KEY_TYPES:
            kept = result.filter(path=f"{name}_items")
            assert kept.differences
            assert kept.diagnostics

    @pytest.mark.parametrize(
        ("key", "expected"),
        [
            pytest.param(float("nan"), "nan", id="nan"),
            pytest.param(float("inf"), "inf", id="inf"),
            pytest.param(float("-inf"), "-inf", id="minus-inf"),
            pytest.param(1.5, "1.5", id="fraction"),
            pytest.param(1e300, "1e+300", id="exponent"),
            pytest.param(b"a\x00", 'b"a\\x00"', id="bytes"),
            pytest.param("a\nb", '"a\\nb"', id="newline"),
            pytest.param("\x1b", '"\\x1b"', id="esc"),
        ],
    )
    def test_float_nan_bytes_and_escaped_keys_render_in_the_grammar(
        self, key: object, expected: str
    ) -> None:
        """The key renders in one spelling, and that spelling parses back."""
        cls = _root_class()
        field = {float: "f64_items", bytes: "raw_items", str: "text_items"}[type(key)]
        left = cls()
        getattr(left, field).add(k=key, v="a")
        d = MessageDifferencer()
        d.treat_as_map(field, key="k")

        result = d.compare(left, cls())

        # A one-sided element reports each populated field of the element.
        assert sorted(str(diff.path) for diff in result) == [
            f"{field}[k={expected}].k", f"{field}[k={expected}].v",
        ]
        for diff in result:
            assert FieldPath.parse(str(diff.path)) == diff.path


# ---------------------------------------------------------------------------
# protokit diff --filter over diagnostics at float- and bytes-keyed paths
# ---------------------------------------------------------------------------


def _cli_file(sub_name: str, key_type: str) -> descriptor_pb2.FileDescriptorProto:
    """``Root { repeated Item items }``, ``Item { k, Sub sub }``; ``Sub`` is named ``sub_name``."""
    text = f"""name: "cli.proto" package: "c" syntax: "proto2"
    message_type {{ name: "{sub_name}"
      field {{ name: "x" number: 1 type: TYPE_INT32 label: LABEL_OPTIONAL }} }}
    message_type {{ name: "Item"
      field {{ name: "k" number: 1 type: {key_type} label: LABEL_OPTIONAL }}
      field {{ name: "sub" number: 2 type: TYPE_MESSAGE type_name: ".c.{sub_name}"
              label: LABEL_OPTIONAL }} }}
    message_type {{ name: "Root"
      field {{ name: "items" number: 1 type: TYPE_MESSAGE type_name: ".c.Item"
              label: LABEL_REPEATED }} }}"""
    return text_format.Parse(text, descriptor_pb2.FileDescriptorProto())


def _cli_side(
    tmp_path: Path, label: str, sub_name: str, key_type: str, key: object, x: int,
) -> tuple[Path, Path]:
    file_proto = _cli_file(sub_name, key_type)
    fds = descriptor_pb2.FileDescriptorSet(file=[file_proto])
    desc = tmp_path / f"{label}.desc"
    desc.write_bytes(fds.SerializeToString())
    pool = descriptor_pool.DescriptorPool()
    pool.Add(file_proto)
    root = message_factory.GetMessageClass(pool.FindMessageTypeByName("c.Root"))()
    item = root.items.add(k=key)
    item.sub.x = x
    data = tmp_path / f"{label}.bin"
    data.write_bytes(root.SerializeToString())
    return desc, data


@pytest.mark.parametrize(
    ("key_type", "key", "bracket"),
    [
        pytest.param("TYPE_DOUBLE", 1.5, "k=1.5", id="float"),
        pytest.param("TYPE_DOUBLE", float("inf"), "k=inf", id="inf"),
        pytest.param("TYPE_BYTES", b'\x00"]', 'k=b"\\x00\\"]"', id="bytes"),
    ],
)
def test_diff_filter_over_keyed_diagnostics_exits_by_its_comparison(
    tmp_path: Path, key_type: str, key: object, bracket: str
) -> None:
    """``--filter`` re-reads diagnostics at a keyed path; the run exits 1, not 2.

    ``--strict-schema`` warns that ``sub``'s type was renamed, at the keyed
    element's path, and ``sub.x`` differs, so the comparison's own exit code
    is 1.
    """
    left_desc, left_bin = _cli_side(tmp_path, "left", "SubA", key_type, key, 1)
    right_desc, right_bin = _cli_side(tmp_path, "right", "SubB", key_type, key, 2)

    result = CliRunner().invoke(main, [
        str(left_bin), str(right_bin),
        "--left-desc", str(left_desc), "--left-type", "c.Root",
        "--right-desc", str(right_desc), "--right-type", "c.Root",
        "--treat-as-map", "items", "k", "--strict-schema",
        "--format", "json", "--filter", "items",
    ])

    assert result.exit_code == 1, result.output
    document = json.loads(result.output)
    assert f"items[{bracket}].sub" in {d["path"] for d in document["diagnostics"]}


# ---------------------------------------------------------------------------
# Field names outside the identifier grammar (hand-built, pure-Python only)
# ---------------------------------------------------------------------------

_upb_refuses_the_name = pytest.mark.skipif(
    api_implementation.Type() == "upb",
    reason="upb refuses a field name outside the identifier grammar when the file is added",
)


def _odd_names_class() -> type[Message]:
    text = """name: "odd.proto" package: "odd" syntax: "proto2"
    message_type { name: "Inner"
      field { name: "foo-bar" number: 1 type: TYPE_STRING label: LABEL_OPTIONAL }
      field { name: "a.b" number: 2 type: TYPE_STRING label: LABEL_OPTIONAL } }
    message_type { name: "Root"
      field { name: "inner" number: 1 type: TYPE_MESSAGE type_name: ".odd.Inner"
              label: LABEL_OPTIONAL }
      field { name: "other" number: 2 type: TYPE_INT32 label: LABEL_OPTIONAL } }"""
    pool = descriptor_pool.DescriptorPool()
    pool.Add(text_format.Parse(text, descriptor_pb2.FileDescriptorProto()))
    return message_factory.GetMessageClass(pool.FindMessageTypeByName("odd.Root"))


@_upb_refuses_the_name
class TestFieldNamesOutsideTheGrammar:
    """A hand-built name the grammar cannot read never makes ``filter`` raise."""

    def _result(self) -> DiffResult:
        cls = _odd_names_class()
        left, right = cls(), cls()
        setattr(left.inner, "foo-bar", "x")
        setattr(right.inner, "foo-bar", "y")
        setattr(left.inner, "a.b", "x")
        left.other, right.other = 1, 2
        d = MessageDifferencer()
        d.register_validate_hook(_warn_everywhere)
        return d.compare(left, right)

    def test_the_names_are_written_as_they_are(self) -> None:
        result = self._result()

        assert sorted(str(diff.path) for diff in result) == [
            "inner.a.b", "inner.foo-bar", "other",
        ]
        assert "inner.foo-bar" in {diagnostic.path for diagnostic in result.diagnostics}

    @pytest.mark.parametrize("exact", [False, True])
    def test_filter_matches_an_unparseable_path_by_its_string_prefix(self, exact: bool) -> None:
        result = self._result()

        inner = result.filter(path="inner", exact=exact)
        other = result.filter(path="other", exact=exact)

        inner_paths = {diagnostic.path for diagnostic in inner.diagnostics}
        if exact:
            assert inner_paths == set()
        else:
            assert {"inner.foo-bar", "inner.a.b"} <= inner_paths
        assert {diagnostic.path for diagnostic in other.diagnostics} == {"other"}
