"""Declared proto2 extensions participate in comparison (U3, V19).

Before U3 the differ could not see a declared extension by any route, and
the two halves failed for *different* reasons — which is why fixing one
alone leaves the defect live:

* **Two-sided comparison** enumerated fields through
  ``_descriptors.get_field_map``, whose ``Descriptor.fields`` source never
  contains extensions. Two messages differing only in an extension value
  compared equal.
* **One-sided emission** walks ``Message.ListFields()``, which *does* yield
  set extensions, and then discarded them with an explicit
  ``if fd.is_extension: continue``. An added or removed message reported
  none of the extensions it carried.

Extensions are emitted under a parenthesized path segment — ``(pkg.ext)`` —
mirroring the proto text format, so an extension is never confusable with a
declared field of the same short name.
"""

from __future__ import annotations

from google.protobuf import descriptor as d
from google.protobuf import descriptor_pb2, descriptor_pool, message_factory
from google.protobuf.message import Message

from protokit.message import MessageDifferencer, diff_messages
from protokit.message.comparators import MessageFieldComparison

_FD = d.FieldDescriptor


def _ext_pool() -> descriptor_pool.DescriptorPool:
    """proto2 ``x.Msg`` with an extension range and two declared extensions."""
    pool = descriptor_pool.DescriptorPool()
    fdp = descriptor_pb2.FileDescriptorProto(name="x.proto", package="x", syntax="proto2")
    msg = fdp.message_type.add(name="Msg")
    msg.field.add(name="name", number=1, type=_FD.TYPE_STRING, label=_FD.LABEL_OPTIONAL)
    msg.extension_range.add(start=100, end=200)
    fdp.extension.add(
        name="tag", number=100, type=_FD.TYPE_STRING,
        label=_FD.LABEL_OPTIONAL, extendee=".x.Msg",
    )
    fdp.extension.add(
        name="rank", number=101, type=_FD.TYPE_INT32,
        label=_FD.LABEL_OPTIONAL, extendee=".x.Msg",
    )
    # An outer message holding x.Msg, for the one-sided (whole-submessage) case.
    outer = fdp.message_type.add(name="Outer")
    outer.field.add(
        name="inner", number=1, type=_FD.TYPE_MESSAGE,
        label=_FD.LABEL_OPTIONAL, type_name=".x.Msg",
    )
    pool.Add(fdp)
    return pool


def _classes() -> tuple[type[Message], type[Message], d.FieldDescriptor, d.FieldDescriptor]:
    pool = _ext_pool()
    msg_cls = message_factory.GetMessageClass(pool.FindMessageTypeByName("x.Msg"))
    outer_cls = message_factory.GetMessageClass(pool.FindMessageTypeByName("x.Outer"))
    return msg_cls, outer_cls, pool.FindExtensionByName("x.tag"), pool.FindExtensionByName("x.rank")


def _rich_pool() -> descriptor_pool.DescriptorPool:
    """``b.Msg`` with a message-typed and a repeated extension."""
    pool = descriptor_pool.DescriptorPool()
    fdp = descriptor_pb2.FileDescriptorProto(name="b.proto", package="b", syntax="proto2")
    sub = fdp.message_type.add(name="Sub")
    sub.field.add(name="v", number=1, type=_FD.TYPE_INT32, label=_FD.LABEL_OPTIONAL)
    msg = fdp.message_type.add(name="Msg")
    msg.field.add(name="name", number=1, type=_FD.TYPE_STRING, label=_FD.LABEL_OPTIONAL)
    msg.extension_range.add(start=100, end=200)
    fdp.extension.add(
        name="subext", number=100, type=_FD.TYPE_MESSAGE,
        label=_FD.LABEL_OPTIONAL, extendee=".b.Msg", type_name=".b.Sub",
    )
    fdp.extension.add(
        name="repext", number=101, type=_FD.TYPE_INT32,
        label=_FD.LABEL_REPEATED, extendee=".b.Msg",
    )
    pool.Add(fdp)
    return pool


def _rich_classes() -> tuple[
    type[Message], type[Message], d.FieldDescriptor, d.FieldDescriptor,
    d.FieldDescriptor, d.FieldDescriptor,
]:
    pool = _rich_pool()
    msg_cls = message_factory.GetMessageClass(pool.FindMessageTypeByName("b.Msg"))
    return (
        msg_cls, msg_cls,
        pool.FindExtensionByName("b.subext"), pool.FindExtensionByName("b.repext"),
        pool.FindExtensionByName("b.subext"), pool.FindExtensionByName("b.repext"),
    )


class TestTwoSidedExtensionComparison:
    def test_differing_extension_value_is_reported(self) -> None:
        """The headline V19 case: equal declared fields, different extension."""
        msg_cls, _outer, tag, _rank = _classes()
        left, right = msg_cls(name="same"), msg_cls(name="same")
        left.Extensions[tag] = "alpha"
        right.Extensions[tag] = "beta"
        result = diff_messages(left, right)
        paths = [str(diff.path) for diff in result]
        assert paths == ["(x.tag)"], f"expected the extension reported, got {paths}"

    def test_equal_extension_values_report_nothing(self) -> None:
        msg_cls, _outer, tag, _rank = _classes()
        left, right = msg_cls(name="same"), msg_cls(name="same")
        left.Extensions[tag] = "alpha"
        right.Extensions[tag] = "alpha"
        assert list(diff_messages(left, right)) == []

    def test_extension_set_on_one_side_only_is_reported(self) -> None:
        msg_cls, _outer, tag, _rank = _classes()
        left, right = msg_cls(name="same"), msg_cls(name="same")
        left.Extensions[tag] = "alpha"
        result = diff_messages(left, right)
        assert [str(diff.path) for diff in result] == ["(x.tag)"]

    def test_every_differing_extension_is_reported(self) -> None:
        """Order follows the differ's existing contract: sorted by path string.

        ``DiffResult`` sorts by ``str(path)`` at the end of a comparison, so
        ``(x.rank)`` precedes ``(x.tag)`` alphabetically even though rank has
        the higher field number. Asserted explicitly because "extensions come
        out in field-number order" is the plausible wrong guess.
        """
        msg_cls, _outer, tag, rank = _classes()
        left, right = msg_cls(name="same"), msg_cls(name="same")
        left.Extensions[tag] = "alpha"
        left.Extensions[rank] = 1
        right.Extensions[tag] = "beta"
        right.Extensions[rank] = 2
        paths = [str(diff.path) for diff in diff_messages(left, right)]
        assert paths == ["(x.rank)", "(x.tag)"], paths


class TestNonScalarExtensions:
    """Message-typed and repeated extensions, which scalar coverage missed.

    Folding extensions into the two-sided name map made the message, repeated
    and treat-as-map comparison branches reachable by an extension descriptor
    for the first time. Those branches read values with
    ``getattr(msg, fd.name)``, which does not work for an extension — its
    value lives in ``msg.Extensions[fd]`` — so both crashed outright
    (``ValueError: Protocol message Msg has no "subext" field.`` and
    ``AttributeError: repext``) until they were routed through the accessors.
    Scalar-only coverage could not catch it, which is why these exist.
    """

    def test_message_typed_extension_is_compared(self) -> None:
        msg_cls, _outer, _tag, _rank, subext, _repext = _rich_classes()
        left, right = msg_cls(name="x"), msg_cls(name="x")
        left.Extensions[subext].v = 1
        right.Extensions[subext].v = 2
        paths = [str(diff.path) for diff in diff_messages(left, right)]
        assert paths == ["(b.subext).v"], paths

    def test_message_typed_extension_equal_reports_nothing(self) -> None:
        msg_cls, _outer, _tag, _rank, subext, _repext = _rich_classes()
        left, right = msg_cls(name="x"), msg_cls(name="x")
        left.Extensions[subext].v = 7
        right.Extensions[subext].v = 7
        assert list(diff_messages(left, right)) == []

    def test_message_typed_extension_on_one_side_only(self) -> None:
        msg_cls, _outer, _tag, _rank, subext, _repext = _rich_classes()
        left, right = msg_cls(name="x"), msg_cls(name="x")
        right.Extensions[subext].v = 3
        paths = [str(diff.path) for diff in diff_messages(left, right)]
        assert paths == ["(b.subext).v"], paths

    def test_repeated_extension_is_compared(self) -> None:
        msg_cls, _outer, _tag, _rank, _subext, repext = _rich_classes()
        left, right = msg_cls(name="x"), msg_cls(name="x")
        left.Extensions[repext].extend([1, 2])
        right.Extensions[repext].extend([1, 9])
        paths = [str(diff.path) for diff in diff_messages(left, right)]
        assert paths == ["(b.repext)[1]"], paths

    def test_repeated_extension_equal_reports_nothing(self) -> None:
        msg_cls, _outer, _tag, _rank, _subext, repext = _rich_classes()
        left, right = msg_cls(name="x"), msg_cls(name="x")
        left.Extensions[repext].extend([4, 5])
        right.Extensions[repext].extend([4, 5])
        assert list(diff_messages(left, right)) == []

    def test_repeated_extension_length_change_is_reported(self) -> None:
        msg_cls, _outer, _tag, _rank, _subext, repext = _rich_classes()
        left, right = msg_cls(name="x"), msg_cls(name="x")
        left.Extensions[repext].extend([1])
        right.Extensions[repext].extend([1, 2])
        assert [str(d.path) for d in diff_messages(left, right)] != []


class TestOneSidedExtensionEmission:
    def test_added_submessage_reports_its_extensions(self) -> None:
        """The ``ListFields`` half: a whole submessage appears on one side."""
        msg_cls, outer_cls, tag, _rank = _classes()
        right = outer_cls()
        right.inner.name = "n"
        right.inner.Extensions[tag] = "alpha"
        paths = [str(diff.path) for diff in diff_messages(outer_cls(), right)]
        assert "inner.(x.tag)" in paths, paths


class TestAdjacentBehaviorUnchanged:
    """KTD3 adjacent-behavior gate for the ``ListFields`` skip removal.

    Changing the one-sided emission loop is exactly the kind of edit that
    silently alters output for messages that have nothing to do with
    extensions. These pin one-sided and all-fields emission on
    extension-free messages so a regression there fails here rather than
    surfacing in an unrelated suite.
    """

    def test_one_sided_emission_unchanged_without_extensions(self) -> None:
        _msg, outer_cls, _tag, _rank = _classes()
        right = outer_cls()
        right.inner.name = "n"
        paths = [str(diff.path) for diff in diff_messages(outer_cls(), right)]
        assert paths == ["inner.name"], paths

    def test_empty_but_present_submessage_follows_presence_mode(self) -> None:
        """Pins presence-mode semantics across the V19 change.

        ``right.inner.SetInParent()`` makes ``HasField("inner")`` true on the
        right and false on the left, and under the default EQUIVALENT
        presence mode the differ reports nothing. That looks like a presence
        fail-open and is not one: EQUIVALENT deliberately treats an
        empty-but-present submessage as equivalent to an absent one, matching
        upstream ``MessageDifferencer::EQUIVALENT``, and EQUAL reports it.
        ``_compare_message_field`` is the single decision site for that
        reconciliation.

        Both modes are asserted here because the V19 edit touches the
        one-sided emission path that sits directly beside this branch, so a
        regression that collapsed the two modes together would otherwise show
        up far from its cause.
        """
        _msg, outer_cls, _tag, _rank = _classes()
        right = outer_cls()
        right.inner.SetInParent()
        assert [str(d.path) for d in diff_messages(outer_cls(), right)] == []

        differ = MessageDifferencer()
        differ.set_message_field_comparison(MessageFieldComparison.EQUAL)
        equal_mode = differ.compare(outer_cls(), right)
        assert [(str(d.path), d.change_type.name) for d in equal_mode] == [
            ("inner", "ADDED"),
        ]

    def test_declared_fields_unchanged_when_an_extension_is_also_present(self) -> None:
        """An extension must not displace or reorder declared-field output."""
        msg_cls, _outer, tag, _rank = _classes()
        left, right = msg_cls(name="a"), msg_cls(name="b")
        left.Extensions[tag] = "alpha"
        right.Extensions[tag] = "alpha"
        paths = [str(diff.path) for diff in diff_messages(left, right)]
        assert paths == ["name"], paths
