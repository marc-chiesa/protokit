"""Comparing two messages never modifies either of them, on either backend.

A repeated extension set on one side only is filed under both sides' field
maps, so the differ reads it from the side that does not hold it as well.
Under upb, reading ``msg.Extensions[ext]`` for a repeated extension the message
does not hold creates an empty container: from then on ``ListFields()`` lists
``(ext, [])`` and the message no longer compares equal to an untouched copy,
though its bytes are unchanged. Pure-Python creates nothing. The caller's
message changed, and so did every later comparison of it, because the differ
asks ``ListFields()`` whether a message is empty: an element that was empty
counted as populated and its ``ADDED`` was dropped.

The read goes through ``_fieldview.field_value``. These tests hold it to
pure-Python's behaviour on both backends: each input equals a pristine copy
after the comparison, and each comparison gives the differences pure-Python
gives.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from dataclasses import dataclass

import pytest
from google.protobuf import descriptor as d
from google.protobuf import descriptor_pb2, descriptor_pool, message_factory
from google.protobuf.message import Message

from protokit.message import MessageDifferencer, diff_messages
from protokit.message.comparators import MessageFieldComparison
from protokit.message.matchers import expect_proto, proto_match

_FD = d.FieldDescriptor


@dataclass(frozen=True)
class _Schema:
    """One pool's classes and extensions for the ``c.proto`` schema."""

    msg: type[Message]
    outer: type[Message]
    sub: type[Message]
    tags: d.FieldDescriptor
    subs: d.FieldDescriptor


def _schema() -> _Schema:
    """A fresh pool holding proto2 ``c.Msg`` and two repeated extensions of it.

    ``c.tags`` is a repeated scalar extension and ``c.subs`` a repeated message
    extension. ``c.Outer`` holds ``c.Msg`` as a repeated and a singular field.
    """
    fdp = descriptor_pb2.FileDescriptorProto(name="c.proto", package="c", syntax="proto2")
    sub = fdp.message_type.add(name="Sub")
    sub.field.add(name="v", number=1, type=_FD.TYPE_INT32, label=_FD.LABEL_OPTIONAL)
    msg = fdp.message_type.add(name="Msg")
    msg.field.add(name="name", number=1, type=_FD.TYPE_STRING, label=_FD.LABEL_OPTIONAL)
    msg.extension_range.add(start=100, end=200)
    outer = fdp.message_type.add(name="Outer")
    outer.field.add(
        name="items", number=1, type=_FD.TYPE_MESSAGE,
        label=_FD.LABEL_REPEATED, type_name=".c.Msg",
    )
    outer.field.add(
        name="inner", number=2, type=_FD.TYPE_MESSAGE,
        label=_FD.LABEL_OPTIONAL, type_name=".c.Msg",
    )
    fdp.extension.add(
        name="tags", number=100, type=_FD.TYPE_INT32,
        label=_FD.LABEL_REPEATED, extendee=".c.Msg",
    )
    fdp.extension.add(
        name="subs", number=101, type=_FD.TYPE_MESSAGE,
        label=_FD.LABEL_REPEATED, extendee=".c.Msg", type_name=".c.Sub",
    )
    pool = descriptor_pool.DescriptorPool()
    pool.Add(fdp)

    def _cls(name: str) -> type[Message]:
        return message_factory.GetMessageClass(pool.FindMessageTypeByName(name))

    # ``c.Sub`` is built before ``c.Msg``: pure-Python cannot add an element of
    # a repeated message extension whose element class does not exist yet.
    sub_cls = _cls("c.Sub")
    return _Schema(
        msg=_cls("c.Msg"), outer=_cls("c.Outer"), sub=sub_cls,
        tags=pool.FindExtensionByName("c.tags"), subs=pool.FindExtensionByName("c.subs"),
    )


def _set_extension(msg: Message, schema: _Schema, kind: str) -> None:
    """Give ``msg`` one element of the ``kind`` repeated extension."""
    if kind == "scalar":
        msg.Extensions[schema.tags].append(1)  # type: ignore[index]
    else:
        msg.Extensions[schema.subs].add(v=1)  # type: ignore[index]


def _snapshot(msg: Message) -> list[tuple[str, object]]:
    """``msg.ListFields()`` as plain data, so a later read cannot alias it."""
    return [
        (field.full_name, list(value) if field.label == _FD.LABEL_REPEATED else value)
        for field, value in msg.ListFields()
    ]


def _pristine(msg: Message) -> Message:
    copy = type(msg)()
    copy.CopyFrom(msg)
    return copy


def _assert_unchanged(msg: Message, pristine: Message, before: list[tuple[str, object]]) -> None:
    assert _snapshot(msg) == before, "the comparison added to the message's ListFields()"
    assert msg == pristine, "the message no longer equals an untouched copy"


def _run_compare(expected: Message, actual: Message) -> None:
    MessageDifferencer().compare(expected, actual)


def _run_diff_messages(expected: Message, actual: Message) -> None:
    diff_messages(expected, actual)


def _run_proto_match(expected: Message, actual: Message) -> None:
    with pytest.raises(AssertionError):
        proto_match(actual, expected)


def _run_proto_match_partial(expected: Message, actual: Message) -> None:
    # Partial asks whether each expected field is present: for a field set on
    # the actual side only, that reads the expected side, which lacks it.
    with contextlib.suppress(AssertionError):
        proto_match(actual, expected, partial=True)


def _run_expect_proto(expected: Message, actual: Message) -> None:
    with pytest.raises(AssertionError):
        expect_proto(expected).matches(actual)


_ENTRY_POINTS: dict[str, Callable[[Message, Message], None]] = {
    "compare": _run_compare,
    "diff_messages": _run_diff_messages,
    "proto_match": _run_proto_match,
    "proto_match_partial": _run_proto_match_partial,
    "expect_proto": _run_expect_proto,
}


@pytest.mark.parametrize("entry", sorted(_ENTRY_POINTS))
@pytest.mark.parametrize("pools", ["same-pool", "cross-pool"])
@pytest.mark.parametrize("side", ["left", "right"])
@pytest.mark.parametrize("kind", ["scalar", "message"])
@pytest.mark.parametrize("nesting", ["top-level", "in-repeated-element"])
def test_inputs_are_unchanged_after_comparison(
    entry: str, pools: str, side: str, kind: str, nesting: str,
) -> None:
    """Neither input changes when a repeated extension is set on one side only."""
    left_schema = _schema()
    right_schema = left_schema if pools == "same-pool" else _schema()

    def _build(schema: _Schema, carries: bool) -> Message:
        if nesting == "top-level":
            msg = schema.msg(name="a")
            target = msg
        else:
            msg = schema.outer()
            target = msg.items.add(name="a")  # type: ignore[attr-defined]
        if carries:
            _set_extension(target, schema, kind)
        return msg

    left = _build(left_schema, carries=side == "left")
    right = _build(right_schema, carries=side == "right")
    left_pristine, right_pristine = _pristine(left), _pristine(right)
    left_before, right_before = _snapshot(left), _snapshot(right)
    left_inner = left if nesting == "top-level" else left.items[0]  # type: ignore[attr-defined]
    right_inner = right if nesting == "top-level" else right.items[0]  # type: ignore[attr-defined]
    left_inner_before, right_inner_before = _snapshot(left_inner), _snapshot(right_inner)

    _ENTRY_POINTS[entry](left, right)

    _assert_unchanged(left, left_pristine, left_before)
    _assert_unchanged(right, right_pristine, right_before)
    assert _snapshot(left_inner) == left_inner_before
    assert _snapshot(right_inner) == right_inner_before


@pytest.mark.parametrize("pools", ["same-pool", "cross-pool"])
def test_treat_as_set_keeps_the_added_element(pools: str) -> None:
    """The one-sided element is still ADDED within the same comparison.

    Comparing the elements reads ``(c.tags)`` of the right-hand element, which
    lacks it. Had that read created an empty container, the element would look
    populated when the set's leftovers are emitted, and its ``ADDED`` would be
    dropped.
    """
    left_schema = _schema()
    right_schema = left_schema if pools == "same-pool" else _schema()
    left = left_schema.outer()
    left.items.add().Extensions[left_schema.tags].append(1)  # type: ignore[attr-defined]
    right = right_schema.outer()
    right.items.add()  # type: ignore[attr-defined]

    differ = MessageDifferencer()
    differ.treat_as_set("items")
    result = differ.compare(left, right)

    assert [(str(diff.path), diff.change_type.name) for diff in result] == [
        ("items[0]", "ADDED"),
        ("items[0].(c.tags)[0]", "REMOVED"),
    ]


@pytest.mark.parametrize("pools", ["same-pool", "cross-pool"])
def test_an_earlier_comparison_does_not_change_a_later_one(pools: str) -> None:
    """The same comparison gives the same answer before and after another one.

    ``right`` holds one empty element. Comparing it against a message whose
    element carries ``(c.tags)`` must not leave that element looking populated,
    or comparing an empty ``Outer`` against ``right`` turns from one ADDED into
    a silent match.
    """
    left_schema = _schema()
    right_schema = left_schema if pools == "same-pool" else _schema()
    right = right_schema.outer()
    right.items.add()  # type: ignore[attr-defined]
    carrier = left_schema.outer()
    carrier.items.add().Extensions[left_schema.tags].append(1)  # type: ignore[attr-defined]

    def _against_empty() -> list[tuple[str, str]]:
        result = MessageDifferencer().compare(left_schema.outer(), right)
        return [(str(diff.path), diff.change_type.name) for diff in result]

    assert _against_empty() == [("items[0]", "ADDED")]
    MessageDifferencer().compare(carrier, right)
    assert _against_empty() == [("items[0]", "ADDED")]


@pytest.mark.parametrize("pools", ["same-pool", "cross-pool"])
def test_equal_presence_still_reports_an_empty_but_present_message(pools: str) -> None:
    """Under EQUAL presence a set, empty ``inner`` is ADDED, however often it is compared.

    Comparing ``right`` against a message whose ``inner`` carries ``(c.tags)``
    reads that extension from ``right.inner``. It must stay empty, or the
    empty-but-present exception no longer applies and its ``ADDED`` is lost.
    """
    left_schema = _schema()
    right_schema = left_schema if pools == "same-pool" else _schema()
    right = right_schema.outer()
    right.inner.SetInParent()  # type: ignore[attr-defined]
    carrier = left_schema.outer()
    carrier.inner.Extensions[left_schema.tags].append(1)  # type: ignore[attr-defined]

    def _against_empty() -> list[tuple[str, str]]:
        differ = MessageDifferencer()
        differ.set_message_field_comparison(MessageFieldComparison.EQUAL)
        result = differ.compare(left_schema.outer(), right)
        return [(str(diff.path), diff.change_type.name) for diff in result]

    assert _against_empty() == [("inner", "ADDED")]
    differ = MessageDifferencer()
    differ.set_message_field_comparison(MessageFieldComparison.EQUAL)
    differ.compare(carrier, right)
    assert _against_empty() == [("inner", "ADDED")]


@pytest.mark.parametrize("kind", ["scalar", "message"])
@pytest.mark.parametrize("side", ["left", "right"])
def test_one_sided_repeated_extension_differences(kind: str, side: str) -> None:
    """The differences reported are pure-Python's, element by element."""
    schema = _schema()
    carrier, bare = schema.msg(name="a"), schema.msg(name="a")
    _set_extension(carrier, schema, kind)
    left, right = (carrier, bare) if side == "left" else (bare, carrier)

    result = MessageDifferencer().compare(left, right)

    change = "REMOVED" if side == "left" else "ADDED"
    path = "(c.tags)[0]" if kind == "scalar" else "(c.subs)[0].v"
    assert [(str(diff.path), diff.change_type.name) for diff in result] == [(path, change)]


def _map_extension_class() -> tuple[type[Message], d.FieldDescriptor]:
    """``m.Msg`` with a map-typed extension, which only in-memory construction reaches.

    ``protoc`` refuses the shape, and upb crashes on ``CopyFrom`` or
    serializing such a message, so the test below never copies or compares one
    whole: it reads ``ListFields()`` only.
    """
    fdp = descriptor_pb2.FileDescriptorProto(name="m.proto", package="m", syntax="proto2")
    msg = fdp.message_type.add(name="Msg")
    msg.field.add(name="name", number=1, type=_FD.TYPE_STRING, label=_FD.LABEL_OPTIONAL)
    msg.extension_range.add(start=100, end=200)
    entry = msg.nested_type.add(name="TagsEntry")
    entry.options.map_entry = True
    entry.field.add(name="key", number=1, type=_FD.TYPE_STRING, label=_FD.LABEL_OPTIONAL)
    entry.field.add(name="value", number=2, type=_FD.TYPE_INT32, label=_FD.LABEL_OPTIONAL)
    fdp.extension.add(
        name="tags", number=100, type=_FD.TYPE_MESSAGE, label=_FD.LABEL_REPEATED,
        extendee=".m.Msg", type_name=".m.Msg.TagsEntry",
    )
    pool = descriptor_pool.DescriptorPool()
    pool.Add(fdp)
    msg_cls = message_factory.GetMessageClass(pool.FindMessageTypeByName("m.Msg"))
    return msg_cls, pool.FindExtensionByName("m.tags")


@pytest.mark.parametrize("side", ["left", "right"])
def test_map_typed_extension_on_one_side_leaves_the_other_unchanged(side: str) -> None:
    """The side without the map-typed extension is read as an empty map, not given one."""
    msg_cls, tags = _map_extension_class()
    carrier, bare = msg_cls(name="a"), msg_cls(name="a")
    carrier.Extensions[tags]["k"] = 2  # type: ignore[index]
    left, right = (carrier, bare) if side == "left" else (bare, carrier)

    result = MessageDifferencer().compare(left, right)

    change = "REMOVED" if side == "left" else "ADDED"
    assert [(str(diff.path), diff.change_type.name) for diff in result] == [
        ('(m.tags)["k"]', change),
    ]
    assert [field.full_name for field, _ in bare.ListFields()] == ["m.Msg.name"]


def test_a_repeated_extension_of_another_pool_is_refused_not_read_as_empty() -> None:
    """An extension from another pool is refused, as the read refused it before.

    ``field_value`` reads an unheld repeated extension as empty only for an
    extension of the message's own type. One resolved in another pool, even
    with the same full name, still raises ``KeyError`` on both backends, so a
    caller that borrowed the other side's descriptor is told, not answered.
    """
    from protokit._fieldview import field_value

    def pool() -> descriptor_pool.DescriptorPool:
        f = descriptor_pb2.FileDescriptorProto(name="c.proto", package="c", syntax="proto2")
        m = f.message_type.add(name="Msg")
        m.extension_range.add(start=100, end=200)
        f.extension.add(
            name="tags", number=100, type=d.FieldDescriptor.TYPE_INT32,
            label=d.FieldDescriptor.LABEL_REPEATED, extendee=".c.Msg",
        )
        p = descriptor_pool.DescriptorPool()
        p.AddSerializedFile(f.SerializeToString())
        return p

    own, other = pool(), pool()
    msg = message_factory.GetMessageClass(own.FindMessageTypeByName("c.Msg"))()

    with pytest.raises(KeyError):
        field_value(msg, other.FindExtensionByName("c.tags"))
    assert msg.ListFields() == []
    assert len(field_value(msg, own.FindExtensionByName("c.tags"))) == 0
    assert msg.ListFields() == []
