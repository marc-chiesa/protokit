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

Extensions are emitted under a parenthesized path segment — ``(pkg.ext)``,
the spelling proto uses for custom options — so an extension is never
confusable with a declared field of the same short name.
"""

from __future__ import annotations

import pytest
from google.protobuf import descriptor as d
from google.protobuf import descriptor_database, descriptor_pb2, descriptor_pool, message_factory
from google.protobuf.message import Message

from protokit.message import DuplicateKeyError, MessageDifferencer, diff_messages
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


def _map_pool() -> descriptor_pool.DescriptorPool:
    """``m.Msg`` with a map-typed extension: ``extend Msg { map<string,int32> tags = 100; }``."""
    pool = descriptor_pool.DescriptorPool()
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
    outer = fdp.message_type.add(name="Outer")
    outer.field.add(
        name="inner", number=1, type=_FD.TYPE_MESSAGE,
        label=_FD.LABEL_OPTIONAL, type_name=".m.Msg",
    )
    pool.Add(fdp)
    return pool


def _map_classes() -> tuple[type[Message], type[Message], d.FieldDescriptor]:
    pool = _map_pool()
    msg_cls = message_factory.GetMessageClass(pool.FindMessageTypeByName("m.Msg"))
    outer_cls = message_factory.GetMessageClass(pool.FindMessageTypeByName("m.Outer"))
    return msg_cls, outer_cls, pool.FindExtensionByName("m.tags")


class TestMapTypedExtension:
    """A map-typed extension reaches the two map branches that still read by name.

    ``is_map_field`` is true for an extension whose type is a map entry, so
    the dispatch sends it into ``_compare_map`` and into the map branch of
    ``_emit_one_sided`` — the two value reads that were left on
    ``getattr(msg, fd.name)`` when every sibling branch moved to
    ``_field_value``. An extension is not an attribute, so both raised
    ``AttributeError`` instead of comparing.

    The shape is deliberately exotic. ``protoc`` refuses to compile it ("map
    fields are not allowed to be extensions") and the Python runtime cannot
    serialize one — measured on protobuf 5.27.5, pure-Python raises from the
    encoder and upb crashes the interpreter on ``SerializeToString`` and
    ``CopyFrom``. It is reachable only by in-memory construction, which is
    why these tests build every message directly and never copy or
    serialize one. The defect it exposes is not exotic: an accessor site
    that a descriptor kind can reach but the code did not expect.
    """

    def test_two_sided_differing_entry_is_reported(self) -> None:
        msg_cls, _outer, tags = _map_classes()
        left, right = msg_cls(name="same"), msg_cls(name="same")
        left.Extensions[tags]["k"] = 1
        right.Extensions[tags]["k"] = 2
        diffs = [(str(x.path), x.change_type.name) for x in diff_messages(left, right)]
        assert diffs == [('(m.tags)["k"]', "MODIFIED")], diffs

    def test_two_sided_equal_reports_nothing(self) -> None:
        msg_cls, _outer, tags = _map_classes()
        left, right = msg_cls(name="same"), msg_cls(name="same")
        left.Extensions[tags]["k"] = 1
        right.Extensions[tags]["k"] = 1
        assert list(diff_messages(left, right)) == []

    def test_set_on_one_side_only_is_reported(self) -> None:
        """Same type on both sides, extension set on one: the ``_emit_one_sided`` route."""
        msg_cls, _outer, tags = _map_classes()
        left, right = msg_cls(name="same"), msg_cls(name="same")
        right.Extensions[tags]["k"] = 2
        diffs = [(str(x.path), x.change_type.name) for x in diff_messages(left, right)]
        assert diffs == [('(m.tags)["k"]', "ADDED")], diffs

    def test_added_submessage_reports_its_map_extension(self) -> None:
        """The ``ListFields`` route already had the value in hand; pinned so it stays that way."""
        _msg, outer_cls, tags = _map_classes()
        right = outer_cls()
        right.inner.name = "n"
        right.inner.Extensions[tags]["k"] = 2
        diffs = [(str(x.path), x.change_type.name) for x in diff_messages(outer_cls(), right)]
        assert diffs == [('inner.(m.tags)["k"]', "ADDED"), ("inner.name", "ADDED")], diffs


class TestIgnoreAndFilterRoundTrip:
    """The path the differ emits must work in the selectors that consume paths.

    The CHANGELOG's mitigation for the BREAKING change is ``--ignore`` on the
    parenthesised path. Until the grammar accepted it, that raised
    ``ValueError`` from ``FieldPath.parse`` — the tool emitted a path it could
    not read back — and so did ``DiffResult.filter`` over any result that
    contained an extension, since it re-parses every difference's path.
    """

    def test_ignore_by_extension_name_suppresses_it_everywhere(self) -> None:
        """A single parenthesised segment is the extension's *name*: global, like a bare name."""
        msg_cls, outer_cls, tag, _rank = _classes()
        differ = MessageDifferencer()
        differ.ignore_fields("(x.tag)")

        left, right = msg_cls(name="same"), msg_cls(name="same")
        left.Extensions[tag] = "alpha"
        right.Extensions[tag] = "beta"
        assert list(differ.compare(left, right)) == []

        added = outer_cls()
        added.inner.name = "n"
        added.inner.Extensions[tag] = "alpha"
        assert [str(d.path) for d in differ.compare(outer_cls(), added)] == ["inner.name"]

    def test_ignore_by_dotted_path_is_scoped(self) -> None:
        msg_cls, outer_cls, tag, _rank = _classes()
        differ = MessageDifferencer()
        differ.ignore_fields("inner.(x.tag)")

        added = outer_cls()
        added.inner.name = "n"
        added.inner.Extensions[tag] = "alpha"
        assert [str(d.path) for d in differ.compare(outer_cls(), added)] == ["inner.name"]

        left, right = msg_cls(name="same"), msg_cls(name="same")
        left.Extensions[tag] = "alpha"
        right.Extensions[tag] = "beta"
        assert [str(d.path) for d in differ.compare(left, right)] == ["(x.tag)"]

    def test_short_name_does_not_ignore_an_extension(self) -> None:
        """Extensions live in their own namespace; ``tag`` is not ``(x.tag)``."""
        msg_cls, _outer, tag, _rank = _classes()
        differ = MessageDifferencer()
        differ.ignore_fields("tag")
        left, right = msg_cls(name="same"), msg_cls(name="same")
        left.Extensions[tag] = "alpha"
        right.Extensions[tag] = "beta"
        assert [str(d.path) for d in differ.compare(left, right)] == ["(x.tag)"]

    def test_conflict_checks_classify_a_parenthesised_name_as_global(self) -> None:
        """The registration-time conflict checks use the same global/scoped rule.

        A parenthesised name contains dots but is one segment, so every site
        that decides "bare name or dotted path" must agree with the partition
        that files it under ``_ignore_names`` — or a conflict the docstrings
        promise to catch slips through for extensions.
        """
        differ = MessageDifferencer()
        differ.ignore_fields("(x.tag)")
        with pytest.raises(ValueError, match="globally ignored"):
            differ.treat_as_map("items", key="(x.tag)")

        differ = MessageDifferencer()
        differ.treat_as_map("items", key="(x.tag)")
        with pytest.raises(ValueError, match="globally"):
            differ.ignore_fields("(x.tag)")

    def test_filter_over_a_result_containing_an_extension(self) -> None:
        msg_cls, _outer, tag, _rank = _classes()
        left, right = msg_cls(name="a"), msg_cls(name="b")
        left.Extensions[tag] = "alpha"
        right.Extensions[tag] = "beta"
        result = diff_messages(left, right)
        assert [str(d.path) for d in result] == ["(x.tag)", "name"]
        assert [str(d.path) for d in result.filter(path="name")] == ["name"]
        assert [str(d.path) for d in result.filter(path="(x.tag)")] == ["(x.tag)"]
        assert [str(d.path) for d in result.filter(path="(x.tag)", exact=True)] == ["(x.tag)"]


def _keyed_pool(package: str = "x") -> descriptor_pool.DescriptorPool:
    """``Msg`` with a declared repeated ``items`` and two repeated-message extensions.

    ``xitems`` elements carry the key field ``id``; ``items`` (an extension
    whose SHORT name collides with the declared field, the collision the
    namespace decision exists to survive) elements do not.
    """
    pool = descriptor_pool.DescriptorPool()
    fdp = descriptor_pb2.FileDescriptorProto(name="k.proto", syntax="proto2")
    if package:
        fdp.package = package
    prefix = f".{package}." if package else "."
    item = fdp.message_type.add(name="Item")
    item.field.add(name="id", number=1, type=_FD.TYPE_STRING, label=_FD.LABEL_OPTIONAL)
    item.field.add(name="v", number=2, type=_FD.TYPE_INT32, label=_FD.LABEL_OPTIONAL)
    noid = fdp.message_type.add(name="NoId")
    noid.field.add(name="v", number=1, type=_FD.TYPE_INT32, label=_FD.LABEL_OPTIONAL)
    msg = fdp.message_type.add(name="Msg")
    msg.field.add(name="name", number=1, type=_FD.TYPE_STRING, label=_FD.LABEL_OPTIONAL)
    msg.field.add(
        name="items", number=2, type=_FD.TYPE_MESSAGE, label=_FD.LABEL_REPEATED,
        type_name=f"{prefix}Item",
    )
    msg.extension_range.add(start=100, end=300)
    fdp.extension.add(
        name="xitems", number=101, type=_FD.TYPE_MESSAGE, label=_FD.LABEL_REPEATED,
        extendee=f"{prefix}Msg", type_name=f"{prefix}Item",
    )
    fdp.extension.add(
        name="items", number=102, type=_FD.TYPE_MESSAGE, label=_FD.LABEL_REPEATED,
        extendee=f"{prefix}Msg", type_name=f"{prefix}NoId",
    )
    outer = fdp.message_type.add(name="Outer")
    outer.field.add(
        name="inner", number=1, type=_FD.TYPE_MESSAGE, label=_FD.LABEL_OPTIONAL,
        type_name=f"{prefix}Msg",
    )
    pool.Add(fdp)
    return pool


def _keyed_classes(package: str = "x") -> tuple[
    type[Message], type[Message], d.FieldDescriptor, d.FieldDescriptor,
]:
    pool = _keyed_pool(package)
    dot = f"{package}." if package else ""
    # Pure-Python needs the element classes materialised before an extension
    # container can ``add()``; harmless under upb.
    message_factory.GetMessageClass(pool.FindMessageTypeByName(f"{dot}Item"))
    message_factory.GetMessageClass(pool.FindMessageTypeByName(f"{dot}NoId"))
    msg_cls = message_factory.GetMessageClass(pool.FindMessageTypeByName(f"{dot}Msg"))
    outer_cls = message_factory.GetMessageClass(pool.FindMessageTypeByName(f"{dot}Outer"))
    return (
        msg_cls, outer_cls,
        pool.FindExtensionByName(f"{dot}xitems"), pool.FindExtensionByName(f"{dot}items"),
    )


def _reordered_pair(cls: type[Message], get_list):  # type: ignore[no-untyped-def]
    left, right = cls(), cls()
    for elem in (get_list(left).add(), get_list(right).add()):
        elem.id, elem.v = "a", 1
    for elem in (get_list(left).add(), get_list(right).add()):
        elem.id, elem.v = "b", 2
    get_list(right)[0].id, get_list(right)[1].id = "b", "a"
    get_list(right)[0].v, get_list(right)[1].v = 2, 1
    return left, right


class TestTreatAsMapOnExtensions:
    """``treat_as_map`` follows the same selector rules as ``ignore_fields``.

    The global-vs-scoped rule and the parenthesised extension key must hold
    at every site that classifies or looks up a selector. Before this was
    pinned, the partition used the dot heuristic (so ``(pkg.ext)`` was a
    root-only path) and both lookups used the descriptor's short name (so a
    bare ``items`` selected an extension named ``items`` — and raised when
    its element type lacked the key).
    """

    def test_global_selector_keys_at_root_and_nested(self) -> None:
        msg_cls, outer_cls, xitems, _items = _keyed_classes()
        differ = MessageDifferencer()
        differ.treat_as_map("(x.xitems)", key="id")
        # One segment is a NAME: it lives in the global table only, never in
        # the path-scoped list (the same partition ``ignore_fields`` applies).
        assert differ._treat_as_map_paths == []
        left, right = _reordered_pair(msg_cls, lambda m: m.Extensions[xitems])
        assert list(differ.compare(left, right)) == []
        ol, orr = _reordered_pair(outer_cls, lambda o: o.inner.Extensions[xitems])
        assert list(differ.compare(ol, orr)) == []

    def test_scoped_selector_applies_only_at_its_location(self) -> None:
        msg_cls, outer_cls, xitems, _items = _keyed_classes()
        differ = MessageDifferencer()
        differ.treat_as_map("inner.(x.xitems)", key="id")
        ol, orr = _reordered_pair(outer_cls, lambda o: o.inner.Extensions[xitems])
        assert list(differ.compare(ol, orr)) == []
        left, right = _reordered_pair(msg_cls, lambda m: m.Extensions[xitems])
        assert len(list(differ.compare(left, right))) == 4

    def test_short_name_never_selects_an_extension(self) -> None:
        """The collision case: a declared ``items`` keyed on ``id`` and an
        extension ``items`` whose elements have no ``id``. The selector must
        apply to the declared field only, so the compare cannot raise."""
        msg_cls, _outer, _xitems, items = _keyed_classes()
        differ = MessageDifferencer()
        differ.treat_as_map("items", key="id")
        left, right = msg_cls(name="n"), msg_cls(name="n")
        left.Extensions[items].add().v = 1
        right.Extensions[items].add().v = 2
        diffs = [(str(x.path), x.change_type.name) for x in differ.compare(left, right)]
        assert diffs == [("(x.items)[0].v", "MODIFIED")], diffs

    def test_package_less_extension_selector(self) -> None:
        msg_cls, _outer, xitems, _items = _keyed_classes(package="")
        differ = MessageDifferencer()
        differ.treat_as_map("(xitems)", key="id")
        left, right = _reordered_pair(msg_cls, lambda m: m.Extensions[xitems])
        assert list(differ.compare(left, right)) == []

    def test_one_sided_emission_honors_the_global_selector(self) -> None:
        """An added submessage renders keyed brackets, not indices."""
        _msg, outer_cls, xitems, _items = _keyed_classes()
        differ = MessageDifferencer()
        differ.treat_as_map("(x.xitems)", key="id")
        added = outer_cls()
        elem = added.inner.Extensions[xitems].add()
        elem.id, elem.v = "a", 1
        paths = sorted(str(x.path) for x in differ.compare(outer_cls(), added))
        assert paths == ['inner.(x.xitems)[id="a"].id', 'inner.(x.xitems)[id="a"].v'], paths


class TestIgnoreFieldsAtomicity:
    def test_failed_registration_leaves_no_partial_state(self) -> None:
        """A rejected call must not poison later configuration.

        The raw-selector list was extended before the dotted selectors were
        parsed, so a malformed selector stayed behind and every later
        ``treat_as_map`` re-parsed it and raised.
        """
        differ = MessageDifferencer()
        with pytest.raises(ValueError):
            differ.ignore_fields("good", "a..b")
        assert differ._ignore_fields_raw == []
        assert differ._ignore_names == set()
        differ.treat_as_map("items", key="id")


class TestExtensionPresenceSemantics:
    """Extensions get the same presence reconciliation as declared fields.

    Only SET extensions can be discovered (``ListFields``), so an extension
    set on one side used to look schema-absent on the other and took the
    one-sided route, which bypasses the EQUIVALENT rule ("a scalar set to its
    default, or an empty message, equals unset") and hands hooks a one-sided context.
    When both sides share a descriptor the extension descriptor reads on
    either message, so it is filed under both names and compared two-sided.
    """

    def test_default_valued_extension_equals_unset_under_equivalent(self) -> None:
        msg_cls, _outer, tag, _rank = _classes()
        left, right = msg_cls(), msg_cls()
        right.Extensions[tag] = ""
        assert list(diff_messages(left, right)) == []

    def test_default_valued_extension_is_added_under_equal(self) -> None:
        msg_cls, _outer, tag, _rank = _classes()
        left, right = msg_cls(), msg_cls()
        right.Extensions[tag] = ""
        differ = MessageDifferencer()
        differ.set_message_field_comparison(MessageFieldComparison.EQUAL)
        assert [(str(x.path), x.change_type.name) for x in differ.compare(left, right)] == [
            ("(x.tag)", "ADDED"),
        ]

    def test_empty_but_present_message_extension_follows_presence_mode(self) -> None:
        msg_cls, _b, subext, _r, _s, _rr = _rich_classes()
        left, right = msg_cls(), msg_cls()
        right.Extensions[subext].SetInParent()
        assert list(diff_messages(left, right)) == []
        differ = MessageDifferencer()
        differ.set_message_field_comparison(MessageFieldComparison.EQUAL)
        assert [(str(x.path), x.change_type.name) for x in differ.compare(left, right)] == [
            ("(b.subext)", "ADDED"),
        ]

    def test_non_default_extension_on_one_side_is_still_reported(self) -> None:
        """Adjacent-behavior gate: the set-vs-unset case keeps its verdict."""
        msg_cls, _outer, tag, _rank = _classes()
        left, right = msg_cls(), msg_cls()
        left.Extensions[tag] = "alpha"
        assert [(str(x.path), x.change_type.name) for x in diff_messages(left, right)] == [
            ("(x.tag)", "REMOVED"),
        ]

    def test_presence_helper_reads_extensions_directly(self) -> None:
        """``_presence`` reads through the seam's accessors, not by name.

        The differ hands ``presence_verdict`` precomputed booleans, so this
        is the only route that exercises the helper's own reads with an
        extension descriptor — and ``HasField(fd.name)`` raises for one.
        """
        from protokit.message._presence import PresenceVerdict, is_set, presence_verdict

        msg_cls, _outer, tag, _rank = _classes()
        left, right = msg_cls(), msg_cls()
        left.Extensions[tag] = ""
        assert is_set(left, tag) is True
        assert is_set(right, tag) is False
        assert presence_verdict(left, right, tag, tag, equal_mode=False) is PresenceVerdict.COLLAPSE
        assert presence_verdict(left, right, tag, tag, equal_mode=True) is PresenceVerdict.REMOVED
        left.Extensions[tag] = "alpha"
        assert presence_verdict(left, right, tag, tag, equal_mode=False) is PresenceVerdict.REMOVED

    def test_hook_context_is_both_sided_for_a_shared_descriptor(self) -> None:
        msg_cls, _outer, tag, _rank = _classes()
        left, right = msg_cls(), msg_cls()
        left.Extensions[tag] = "alpha"
        seen = []
        differ = MessageDifferencer()
        differ.register_report_hook(
            lambda ctx: seen.append((
                str(ctx.path),
                ctx.left_fd is not None, ctx.right_fd is not None,
                ctx.left_msg is not None, ctx.right_msg is not None,
            )),
        )
        differ.compare(left, right)
        assert seen == [("(x.tag)", True, True, True, True)], seen


class TestFloatOverlayOnMapExtension:
    def test_predicate_overlay_sees_the_extension_descriptor(self) -> None:
        """The container lookup for a map value must resolve a parenthesised segment."""
        from protokit.message.comparators import FloatComparison

        pool = descriptor_pool.DescriptorPool()
        fdp = descriptor_pb2.FileDescriptorProto(name="f.proto", package="f", syntax="proto2")
        msg = fdp.message_type.add(name="Msg")
        msg.extension_range.add(start=100, end=200)
        entry = msg.nested_type.add(name="TagsEntry")
        entry.options.map_entry = True
        entry.field.add(name="key", number=1, type=_FD.TYPE_STRING, label=_FD.LABEL_OPTIONAL)
        entry.field.add(name="value", number=2, type=_FD.TYPE_FLOAT, label=_FD.LABEL_OPTIONAL)
        fdp.extension.add(
            name="tags", number=100, type=_FD.TYPE_MESSAGE, label=_FD.LABEL_REPEATED,
            extendee=".f.Msg", type_name=".f.Msg.TagsEntry",
        )
        pool.Add(fdp)
        msg_cls = message_factory.GetMessageClass(pool.FindMessageTypeByName("f.Msg"))
        tags = pool.FindExtensionByName("f.tags")
        left, right = msg_cls(), msg_cls()
        left.Extensions[tags]["k"] = 1.0
        right.Extensions[tags]["k"] = 1.01
        seen = []
        differ = MessageDifferencer()
        differ.set_float_comparison(
            FloatComparison.APPROXIMATE, margin=0.1,
            selector=lambda fd, path: seen.append(fd.full_name) or fd.is_extension,
        )
        assert list(differ.compare(left, right)) == []
        assert seen == ["f.tags"], seen

    def test_predicate_overlay_sees_the_extension_for_a_top_level_entry(self) -> None:
        """The entry of a map extension need not be nested under any message.

        Only a hand-built descriptor can declare a map extension, so its entry
        may sit at file scope, with no parent message to look through. The
        lookup used to give up there and hand the predicate the entry's
        ``value`` field instead of the extension.
        """
        from protokit.message.comparators import FloatComparison

        pool = descriptor_pool.DescriptorPool()
        fdp = descriptor_pb2.FileDescriptorProto(name="t.proto", package="t", syntax="proto2")
        msg = fdp.message_type.add(name="Msg")
        msg.extension_range.add(start=100, end=200)
        entry = fdp.message_type.add(name="TagsEntry")
        entry.options.map_entry = True
        entry.field.add(name="key", number=1, type=_FD.TYPE_STRING, label=_FD.LABEL_OPTIONAL)
        entry.field.add(name="value", number=2, type=_FD.TYPE_FLOAT, label=_FD.LABEL_OPTIONAL)
        fdp.extension.add(
            name="tags", number=100, type=_FD.TYPE_MESSAGE, label=_FD.LABEL_REPEATED,
            extendee=".t.Msg", type_name=".t.TagsEntry",
        )
        pool.Add(fdp)
        msg_cls = message_factory.GetMessageClass(pool.FindMessageTypeByName("t.Msg"))
        tags = pool.FindExtensionByName("t.tags")
        left, right = msg_cls(), msg_cls()
        left.Extensions[tags]["k"] = 1.0
        right.Extensions[tags]["k"] = 1.01
        seen = []
        differ = MessageDifferencer()
        differ.set_float_comparison(
            FloatComparison.APPROXIMATE, margin=0.1,
            selector=lambda fd, path: seen.append(fd.full_name) or fd.is_extension,
        )
        assert list(differ.compare(left, right)) == []
        assert seen == ["t.tags"], seen


def _msg_class_declaring_xitems_on(extendee: str | None) -> type[Message]:
    """``x.Msg`` from a pool that declares ``x.xitems`` on ``extendee``, or not at all."""
    pool = descriptor_pool.DescriptorPool()
    fdp = descriptor_pb2.FileDescriptorProto(name="k2.proto", package="x", syntax="proto2")
    item = fdp.message_type.add(name="Item")
    item.field.add(name="id", number=1, type=_FD.TYPE_STRING, label=_FD.LABEL_OPTIONAL)
    item.field.add(name="v", number=2, type=_FD.TYPE_INT32, label=_FD.LABEL_OPTIONAL)
    for msg_name in ("Msg", "Other"):
        msg = fdp.message_type.add(name=msg_name)
        msg.field.add(name="name", number=1, type=_FD.TYPE_STRING, label=_FD.LABEL_OPTIONAL)
        msg.field.add(
            name="items", number=2, type=_FD.TYPE_MESSAGE, label=_FD.LABEL_REPEATED,
            type_name=".x.Item",
        )
        msg.extension_range.add(start=100, end=300)
    if extendee is not None:
        fdp.extension.add(
            name="xitems", number=101, type=_FD.TYPE_MESSAGE, label=_FD.LABEL_REPEATED,
            extendee=f".x.{extendee}", type_name=".x.Item",
        )
    pool.Add(fdp)
    message_factory.GetMessageClass(pool.FindMessageTypeByName("x.Item"))
    return message_factory.GetMessageClass(pool.FindMessageTypeByName("x.Msg"))


class TestCrossPoolExtensions:
    """An extension both pools declare compares two-sided, as a declared field does.

    Extensions are discovered per side from ``ListFields``, so one set only
    on the right looked schema-absent on the left and took the one-sided
    route — which enumerates by index, never consults ``treat_as_map``, and
    skips its duplicate-key check. The shared-descriptor fold-in closed that
    for one class only; two pools declaring the same extension now resolve it
    each from their own pool by full name. A pool that does not declare it on
    this message keeps the one-sided route, as for any schema-absent field.
    """

    def test_keyed_across_pools_validates_duplicate_keys(self) -> None:
        left_cls, _o, _x, _i = _keyed_classes()
        right_cls, _o2, xitems, _i2 = _keyed_classes()
        left, right = left_cls(), right_cls()
        right.Extensions[xitems].add(id="a", v=1)
        right.Extensions[xitems].add(id="a", v=2)
        differ = MessageDifferencer()
        differ.treat_as_map("(x.xitems)", key="id")
        with pytest.raises(DuplicateKeyError):
            differ.compare(left, right)

    def test_keyed_across_pools_matches_the_shared_descriptor_output(self) -> None:
        def run(left: Message, right: Message, xitems: d.FieldDescriptor) -> list[tuple[str, str]]:
            right.Extensions[xitems].add(id="a", v=1)
            differ = MessageDifferencer()
            differ.treat_as_map("(x.xitems)", key="id")
            return [(str(x.path), x.change_type.name) for x in differ.compare(left, right)]

        one_cls, _o, xitems, _i = _keyed_classes()
        shared = run(one_cls(), one_cls(), xitems)
        left_cls, _o1, _x1, _i1 = _keyed_classes()
        right_cls, _o2, xitems2, _i2 = _keyed_classes()
        assert run(left_cls(), right_cls(), xitems2) == shared == [
            ('(x.xitems)[id="a"].id', "ADDED"), ('(x.xitems)[id="a"].v', "ADDED"),
        ]

    def test_presence_mode_applies_across_pools(self) -> None:
        left_cls, _o, _t, _r = _classes()
        right_cls, _o2, tag, _r2 = _classes()
        left, right = left_cls(), right_cls()
        right.Extensions[tag] = ""
        assert list(diff_messages(left, right)) == []
        differ = MessageDifferencer()
        differ.set_message_field_comparison(MessageFieldComparison.EQUAL)
        assert [(str(x.path), x.change_type.name) for x in differ.compare(left, right)] == [
            ("(x.tag)", "ADDED"),
        ]

    def test_hook_context_is_both_sided_across_pools(self) -> None:
        left_cls, _o, tag, _r = _classes()
        right_cls, _o2, _t2, _r2 = _classes()
        left, right = left_cls(), right_cls()
        left.Extensions[tag] = "alpha"
        seen = []
        differ = MessageDifferencer()
        differ.register_report_hook(
            lambda ctx: seen.append((
                str(ctx.path),
                ctx.left_fd is not None, ctx.right_fd is not None,
                ctx.left_msg is not None, ctx.right_msg is not None,
            )),
        )
        differ.compare(left, right)
        assert seen == [("(x.tag)", True, True, True, True)], seen

    def test_extension_the_other_pool_does_not_declare_stays_one_sided(self) -> None:
        left_cls = _msg_class_declaring_xitems_on(None)
        right_cls, _o, xitems, _i = _keyed_classes()
        left, right = left_cls(), right_cls()
        right.Extensions[xitems].add(id="a", v=1)
        differ = MessageDifferencer()
        differ.treat_as_map("(x.xitems)", key="id")
        assert [(str(x.path), x.change_type.name) for x in differ.compare(left, right)] == [
            ("(x.xitems)[0].id", "ADDED"), ("(x.xitems)[0].v", "ADDED"),
        ]

    def test_extension_declared_on_another_message_stays_one_sided(self) -> None:
        """Same full name, different extendee: not this message's extension."""
        left_cls = _msg_class_declaring_xitems_on("Other")
        right_cls, _o, xitems, _i = _keyed_classes()
        left, right = left_cls(), right_cls()
        right.Extensions[xitems].add(id="a", v=1)
        differ = MessageDifferencer()
        differ.treat_as_map("(x.xitems)", key="id")
        assert [(str(x.path), x.change_type.name) for x in differ.compare(left, right)] == [
            ("(x.xitems)[0].id", "ADDED"), ("(x.xitems)[0].v", "ADDED"),
        ]

    def test_extension_the_other_pool_cannot_build_stays_one_sided(self) -> None:
        """A lazy lookup that fails to build is "not declared", on both backends.

        A pool backed by a descriptor database loads a file at lookup time.
        When that file does not build, pure-Python raises ``KeyError`` and
        upb raises ``TypeError`` from the same call; either way the pool
        does not declare the extension, and the comparison must keep the
        one-sided route it took before the fold-in existed.
        """
        def base(name: str) -> descriptor_pb2.FileDescriptorProto:
            fdp = descriptor_pb2.FileDescriptorProto(name=name, package="x", syntax="proto2")
            msg = fdp.message_type.add(name="Msg")
            msg.field.add(name="name", number=1, type=_FD.TYPE_STRING, label=_FD.LABEL_OPTIONAL)
            msg.extension_range.add(start=100, end=300)
            return fdp

        left_pool = descriptor_pool.DescriptorPool()
        fdp = base("l.proto")
        fdp.extension.add(
            name="xtag", number=102, type=_FD.TYPE_STRING, label=_FD.LABEL_OPTIONAL,
            extendee=".x.Msg",
        )
        left_pool.Add(fdp)
        left_cls = message_factory.GetMessageClass(left_pool.FindMessageTypeByName("x.Msg"))
        xtag = left_pool.FindExtensionByName("x.xtag")

        db = descriptor_database.DescriptorDatabase()
        db.Add(base("r.proto"))
        broken = descriptor_pb2.FileDescriptorProto(name="rext.proto", package="x", syntax="proto2")
        broken.dependency.append("r.proto")
        broken.extension.add(
            name="xtag", number=102, type=_FD.TYPE_STRING, label=_FD.LABEL_OPTIONAL,
            extendee=".x.Missing",
        )
        db.Add(broken)
        right_pool = descriptor_pool.DescriptorPool(db)
        right_cls = message_factory.GetMessageClass(right_pool.FindMessageTypeByName("x.Msg"))
        with pytest.raises((KeyError, TypeError)):
            right_pool.FindExtensionByName("x.xtag")

        left, right = left_cls(), right_cls()
        left.Extensions[xtag] = "a"
        assert [(str(x.path), x.change_type.name) for x in diff_messages(left, right)] == [
            ("(x.xtag)", "REMOVED"),
        ]


def _group_ext_schema() -> descriptor_pb2.FileDescriptorProto:
    """proto2 ``t.M`` extended by a group-typed extension ``t.ext`` (type ``t.Ext``)."""
    f = descriptor_pb2.FieldDescriptorProto
    fdp = descriptor_pb2.FileDescriptorProto(name="ge.proto", package="t", syntax="proto2")
    msg = fdp.message_type.add(name="M")
    msg.field.add(name="name", number=1, type=f.TYPE_STRING, label=f.LABEL_OPTIONAL)
    msg.extension_range.add(start=100, end=200)
    ext_type = fdp.message_type.add(name="Ext")
    ext_type.field.add(name="a", number=1, type=f.TYPE_INT32, label=f.LABEL_OPTIONAL)
    fdp.extension.add(
        name="ext", number=100, type=f.TYPE_GROUP, label=f.LABEL_OPTIONAL,
        type_name=".t.Ext", extendee=".t.M",
    )
    return fdp


def _group_ext_message(a: int) -> Message:
    """A ``t.M`` from a fresh pool, with the group extension's ``a`` set."""
    pool = descriptor_pool.DescriptorPool()
    pool.Add(_group_ext_schema())
    cls = message_factory.GetMessageClass(pool.FindMessageTypeByName("t.M"))
    msg = cls(name="n")
    msg.Extensions[pool.FindExtensionByName("t.ext")].a = a
    return msg


class TestGroupTypedExtension:
    """A group-typed extension is walked like a message-typed one, across pools too."""

    def test_identical_group_extensions_from_two_pools_are_equal(self) -> None:
        result = MessageDifferencer().compare(_group_ext_message(1), _group_ext_message(1))
        assert result.differences == ()

    def test_an_inner_change_is_reported_under_the_extension_key(self) -> None:
        result = MessageDifferencer().compare(_group_ext_message(1), _group_ext_message(2))
        assert [(str(d.path), d.change_type.value) for d in result.differences] == [
            ("(t.ext).a", "MODIFIED"),
        ]

    @pytest.mark.parametrize(("right_a", "exit_code"), [(1, 0), (2, 1)])
    def test_the_cli_compares_group_extensions_across_descriptor_sets(
        self, tmp_path, right_a: int, exit_code: int,
    ) -> None:
        from click.testing import CliRunner

        from protokit.message.cli import main

        desc = descriptor_pb2.FileDescriptorSet()
        desc.file.add().CopyFrom(_group_ext_schema())
        paths = {}
        for side, a in (("left", 1), ("right", right_a)):
            (tmp_path / f"{side}.desc").write_bytes(desc.SerializeToString())
            (tmp_path / f"{side}.pb").write_bytes(_group_ext_message(a).SerializeToString())
            paths[side] = tmp_path / side
        result = CliRunner().invoke(main, [
            f"{paths['left']}.pb", f"{paths['right']}.pb",
            "--left-desc", f"{paths['left']}.desc", "--right-desc", f"{paths['right']}.desc",
            "--left-type", "t.M", "--right-type", "t.M",
        ])
        assert result.exit_code == exit_code, result.output
        if exit_code:
            assert "(t.ext).a" in result.output


# ---------------------------------------------------------------------------
# A lone extension selector ``(pkg.ext)`` selects at any depth in every policy
#
# ``ignore_fields`` and ``treat_as_map`` filed a one-segment ``(pkg.ext)``
# under the extension's name and so applied it everywhere, but the policies
# that take a ``FieldSelector`` (``treat_as_set``, float overlays, and the
# selector form of ``ignore_fields``) matched it exact-length, at the root
# only. The same spelling meant two things, and the registration guards that
# compare selectors missed the overlap.
# ---------------------------------------------------------------------------


def _sel_pool() -> descriptor_pool.DescriptorPool:
    """proto2 ``e.Msg`` with a double, a repeated string and a repeated message extension."""
    pool = descriptor_pool.DescriptorPool()
    fdp = descriptor_pb2.FileDescriptorProto(name="e.proto", package="e", syntax="proto2")
    item = fdp.message_type.add(name="Item")
    item.field.add(name="id", number=1, type=_FD.TYPE_STRING, label=_FD.LABEL_OPTIONAL)
    msg = fdp.message_type.add(name="Msg")
    msg.field.add(name="name", number=1, type=_FD.TYPE_STRING, label=_FD.LABEL_OPTIONAL)
    msg.extension_range.add(start=100, end=200)
    fdp.extension.add(
        name="ival", number=100, type=_FD.TYPE_DOUBLE, label=_FD.LABEL_OPTIONAL,
        extendee=".e.Msg",
    )
    fdp.extension.add(
        name="itags", number=101, type=_FD.TYPE_STRING, label=_FD.LABEL_REPEATED,
        extendee=".e.Msg",
    )
    outer = fdp.message_type.add(name="Outer")
    outer.field.add(
        name="inner", number=1, type=_FD.TYPE_MESSAGE, label=_FD.LABEL_OPTIONAL,
        type_name=".e.Msg",
    )
    pool.Add(fdp)
    return pool


def _sel_pair(
    ival: tuple[float, float] = (1.0, 1.0),
    itags: tuple[list[str], list[str]] = ([], []),
) -> tuple[Message, Message]:
    """Two ``e.Outer`` messages whose ``inner`` carries the given extension values."""
    pool = _sel_pool()
    outer_cls = message_factory.GetMessageClass(pool.FindMessageTypeByName("e.Outer"))
    ival_fd, itags_fd = pool.FindExtensionByName("e.ival"), pool.FindExtensionByName("e.itags")
    pair = []
    for value, tags in zip(ival, itags, strict=True):
        msg = outer_cls()
        msg.inner.name = "n"
        msg.inner.Extensions[ival_fd] = value
        msg.inner.Extensions[itags_fd].extend(tags)
        pair.append(msg)
    return pair[0], pair[1]


def _as_selector(spelling: str, form: str):  # type: ignore[no-untyped-def]
    from protokit.message._selector import FieldSelector

    return FieldSelector.of(spelling) if form == "selector" else spelling


_FORMS = pytest.mark.parametrize("form", ["string", "selector"])


class TestExtensionSelectorAtAnyDepth:
    @_FORMS
    def test_an_exact_float_overlay_applies_to_a_nested_extension(self, form: str) -> None:
        """Global tolerance with an EXACT overlay on the extension: a nested change is found."""
        from protokit.message.comparators import FloatComparison

        left, right = _sel_pair(ival=(1.0, 1.0000001))
        differ = MessageDifferencer()
        differ.set_float_comparison(FloatComparison.APPROXIMATE, fraction=1e-3)
        differ.set_float_comparison(
            FloatComparison.EXACT, selector=_as_selector("(e.ival)", form),
        )
        result = differ.compare(left, right)
        assert result.has_changes()
        assert [str(x.path) for x in result] == ["inner.(e.ival)"]

    @_FORMS
    def test_a_tolerance_overlay_applies_to_a_nested_extension(self, form: str) -> None:
        from protokit.message.comparators import FloatComparison

        left, right = _sel_pair(ival=(1.0, 1.0001))
        differ = MessageDifferencer()
        differ.set_float_comparison(
            FloatComparison.APPROXIMATE, fraction=1e-3, selector=_as_selector("(e.ival)", form),
        )
        assert list(differ.compare(left, right)) == []

    @pytest.mark.parametrize(
        ("first", "second", "has_changes"),
        [
            ("(e.ival)", "inner.(e.ival)", False),  # the lone name registered first wins
            ("inner.(e.ival)", "(e.ival)", True),  # the qualified path registered first wins
        ],
    )
    def test_overlapping_float_overlays_are_first_registered_wins(
        self, first: str, second: str, has_changes: bool,
    ) -> None:
        from protokit.message.comparators import FloatComparison

        left, right = _sel_pair(ival=(1.0, 1.0001))
        differ = MessageDifferencer()
        modes = {
            "(e.ival)": FloatComparison.APPROXIMATE,
            "inner.(e.ival)": FloatComparison.EXACT,
        }
        for selector in (first, second):
            differ.set_float_comparison(modes[selector], fraction=1e-3, selector=selector)
        assert differ.compare(left, right).has_changes() is has_changes

    @_FORMS
    def test_treat_as_set_applies_to_a_nested_extension(self, form: str) -> None:
        left, right = _sel_pair(itags=(["a", "b"], ["b", "a"]))
        differ = MessageDifferencer()
        differ.treat_as_set(_as_selector("(e.itags)", form))
        assert list(differ.compare(left, right)) == []

    def test_treat_as_set_reports_leftovers_of_a_nested_extension(self) -> None:
        left, right = _sel_pair(itags=(["a", "b"], ["c", "a"]))
        differ = MessageDifferencer()
        differ.treat_as_set("(e.itags)")
        assert sorted((str(x.path), x.change_type.name) for x in differ.compare(left, right)) == [
            ("inner.(e.itags)[0]", "ADDED"),
            ("inner.(e.itags)[1]", "REMOVED"),
        ]

    @_FORMS
    def test_ignore_applies_to_a_nested_extension(self, form: str) -> None:
        left, right = _sel_pair(ival=(1.0, 2.0))
        differ = MessageDifferencer()
        differ.ignore_fields(_as_selector("(e.ival)", form))
        assert list(differ.compare(left, right)) == []

    def test_a_qualified_extension_path_stays_scoped(self) -> None:
        """Only the lone name is global; ``other.(e.ival)`` does not reach ``inner``."""
        from protokit.message._selector import FieldSelector

        left, right = _sel_pair(ival=(1.0, 2.0))
        differ = MessageDifferencer()
        differ.ignore_fields(FieldSelector.of("other.(e.ival)"))
        assert [str(x.path) for x in differ.compare(left, right)] == ["inner.(e.ival)"]

    def test_a_bracketed_selector_form_is_still_accepted(self) -> None:
        """Only the string grammar rejects brackets; a bracketed FieldSelector keeps working."""
        from protokit.message._selector import FieldSelector

        left, right = _sel_pair(itags=(["a"], ["b"]))
        differ = MessageDifferencer()
        differ.ignore_fields(FieldSelector.of("inner.(e.itags)[0]"))
        assert list(differ.compare(left, right)) == []

    def test_a_plain_selector_form_name_stays_top_level(self) -> None:
        """Only extension names widen; a plain FieldSelector name keeps exact-length matching."""
        from protokit.message._selector import FieldSelector

        left, right = _sel_pair()
        right.inner.name = "changed"
        differ = MessageDifferencer()
        differ.ignore_fields(FieldSelector.of("name"))
        assert [str(x.path) for x in differ.compare(left, right)] == ["inner.name"]

    def test_a_matcher_tolerance_overlay_applies_to_a_nested_extension(self) -> None:
        from protokit.message import expect_proto

        left, right = _sel_pair(ival=(1.0, 1.0001))
        expect_proto(left).approximately(fraction=1e-3, selector="(e.ival)").assert_matches(right)
        with pytest.raises(AssertionError):
            expect_proto(left).approximately(fraction=1e-3, selector="other").assert_matches(right)

    def test_matchers_apply_the_extension_selector_at_any_depth(self) -> None:
        from protokit.message import proto_match

        left, right = _sel_pair(ival=(1.0, 2.0), itags=(["a", "b"], ["b", "a"]))
        proto_match(right, left, ignore="(e.ival)", as_set="(e.itags)")
        with pytest.raises(AssertionError):
            proto_match(right, left, as_set="(e.itags)")


def _register(differ: MessageDifferencer, call: tuple) -> None:  # type: ignore[type-arg]
    kind, *args = call
    if kind == "set":
        differ.treat_as_set(args[0])
    elif kind == "map":
        differ.treat_as_map(args[0], key=args[1])
    else:
        differ.ignore_fields(args[0])


class TestExtensionSelectorConflicts:
    """A registration that overlaps another through the extension spelling is rejected."""

    @pytest.mark.parametrize(
        ("set_sel", "map_sel"),
        [("(e.items)", "inner.(e.items)"), ("inner.(e.items)", "(e.items)")],
    )
    @pytest.mark.parametrize("set_first", [True, False])
    def test_set_and_map_on_the_same_extension_are_rejected(
        self, set_sel: str, map_sel: str, set_first: bool,
    ) -> None:
        calls = [("set", set_sel), ("map", map_sel, "id")]
        differ = MessageDifferencer()
        _register(differ, calls[0] if set_first else calls[1])
        with pytest.raises(ValueError, match="treat_as_(set|map)"):
            _register(differ, calls[1] if set_first else calls[0])

    @_FORMS
    @pytest.mark.parametrize("ignore", ["(e.items)", "container.(e.items)"])
    @pytest.mark.parametrize("map_first", [True, False])
    def test_ignoring_a_keyed_extension_is_rejected(
        self, ignore: str, map_first: bool, form: str,
    ) -> None:
        calls = [("map", "(e.items)", "id"), ("ignore", _as_selector(ignore, form))]
        differ = MessageDifferencer()
        _register(differ, calls[0] if map_first else calls[1])
        with pytest.raises(ValueError, match="treat_as_map"):
            _register(differ, calls[1] if map_first else calls[0])

    @pytest.mark.parametrize(
        ("ignore", "form"),
        [
            ("container.(e.items).id", "string"),
            ("container.(e.items).id", "selector"),
            ("(e.items).id", "string"),
            ("(e.items).id", "selector"),
            ("id", "string"),  # a plain FieldSelector "id" is top-level only
        ],
    )
    @pytest.mark.parametrize("map_first", [True, False])
    def test_ignoring_the_key_of_a_keyed_extension_is_rejected(
        self, ignore: str, form: str, map_first: bool,
    ) -> None:
        calls = [("map", "(e.items)", "id"), ("ignore", _as_selector(ignore, form))]
        differ = MessageDifferencer()
        _register(differ, calls[0] if map_first else calls[1])
        with pytest.raises(ValueError, match="treat_as_map|key"):
            _register(differ, calls[1] if map_first else calls[0])

    @pytest.mark.parametrize(
        "calls",
        [
            # A scoped map selector does not reach another location's key.
            [("map", "inner.(e.items)", "id"), ("ignore", "container.(e.items).id")],
            # A different extension's key is not this map's key.
            [("map", "(e.items)", "id"), ("ignore", "container.(e.other).id")],
            # A set on one scoped location and a map on another do not overlap.
            [("set", "a.(e.items)"), ("map", "b.(e.items)", "id")],
        ],
    )
    def test_non_overlapping_registrations_are_accepted(self, calls) -> None:  # type: ignore[no-untyped-def]
        for ordered in (calls, calls[::-1]):
            differ = MessageDifferencer()
            for call in ordered:
                _register(differ, call)

    @pytest.mark.parametrize(
        "calls",
        [
            [("map", "parent.items[0]", "id"), ("ignore", "parent.items")],
            [("map", "items", "id"), ("ignore", "container.items")],
        ],
    )
    def test_plain_selectors_keep_the_equal_string_check(self, calls) -> None:  # type: ignore[no-untyped-def]
        """Without an extension name, only equal selector strings conflict, as before.

        Widening the check for plain names (audit finding U8-5 and its
        relatives) is scheduled for 0.17.0; this wave widens it only for the
        extension spelling.
        """
        for ordered in (calls, calls[::-1]):
            differ = MessageDifferencer()
            for call in ordered:
                _register(differ, call)

    def test_a_malformed_map_selector_reports_the_existing_conflict_first(self) -> None:
        """The widened key check must not change which error a bad map selector gets."""
        differ = MessageDifferencer()
        differ.ignore_fields("parent.id", "id")
        with pytest.raises(ValueError, match="'id' is globally ignored"):
            differ.treat_as_map("bad.", key="id")

    @pytest.mark.parametrize("ignore", ["container.(e.items)[0].id", "(e.items)[0]"])
    @pytest.mark.parametrize("map_first", [True, False])
    def test_a_bracketed_selector_form_is_checked_too(self, ignore: str, map_first: bool) -> None:
        """Path-form matching ignores brackets, so the conflict check must too."""
        from protokit.message._selector import FieldSelector

        calls = [("map", "(e.items)", "id"), ("ignore", FieldSelector.of(ignore))]
        differ = MessageDifferencer()
        _register(differ, calls[0] if map_first else calls[1])
        with pytest.raises(ValueError, match="treat_as_map"):
            _register(differ, calls[1] if map_first else calls[0])

    @pytest.mark.parametrize(
        ("first", "second"),
        [
            ("(e.items)", "inner.(e.items)"),
            ("inner.(e.items)", "(e.items)"),
            ("inner.(e.items)", "inner.(e.items)[0]"),
            ("inner.(e.items)[0]", "inner.(e.items)"),
        ],
    )
    def test_two_maps_on_one_extension_must_share_a_key(self, first: str, second: str) -> None:
        differ = MessageDifferencer()
        differ.treat_as_map(first, key="id")
        with pytest.raises(ValueError, match="already configured with key 'id'"):
            differ.treat_as_map(second, key="other")
        same_key = MessageDifferencer()
        same_key.treat_as_map(first, key="id")
        same_key.treat_as_map(second, key="id")

    def test_a_same_key_map_after_a_scoped_one_still_applies_everywhere(self) -> None:
        """The later lone-name map is registered, not dropped as a repeat of the scoped one."""
        msg_cls, _outer, xitems, _items = _keyed_classes()
        differ = MessageDifferencer()
        differ.treat_as_map("inner.(x.xitems)", key="id")
        differ.treat_as_map("(x.xitems)", key="id")
        left, right = _reordered_pair(msg_cls, lambda m: m.Extensions[xitems])
        assert list(differ.compare(left, right)) == []

    def test_two_maps_on_plain_names_keep_the_equal_string_check(self) -> None:
        """Plain names conflict only when equal, as before (widening them is 0.17.0)."""
        differ = MessageDifferencer()
        differ.treat_as_map("items", key="id")
        differ.treat_as_map("inner.items", key="other")
