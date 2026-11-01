"""Tests for treat_as_map key-based repeated field matching."""

import pytest
from google.protobuf import descriptor_pb2, descriptor_pool, message_factory

from protokit.message import (
    ChangeType,
    DuplicateKeyError,
    InvalidKeyFieldError,
    MessageDifferencer,
    MissingKeyError,
)
from tests.proto_builder import ProtoBuilder

T = descriptor_pb2.FieldDescriptorProto


def _make_items_builder() -> ProtoBuilder:
    """Message with repeated Item keyed by 'id'."""
    builder = ProtoBuilder()
    builder.message("test.Item", {
        "id": (T.TYPE_STRING, 1),
        "value": (T.TYPE_INT32, 2),
    })
    builder.message_with_repeated(
        "test.Container",
        {"items": (T.TYPE_MESSAGE, 1, ".test.Item")},
        repeated_fields={"items"},
    )
    return builder


def _make_int_key_builder() -> ProtoBuilder:
    """Message with repeated Entry keyed by int 'key'."""
    builder = ProtoBuilder()
    builder.message("test.Entry", {
        "key": (T.TYPE_INT32, 1),
        "name": (T.TYPE_STRING, 2),
    })
    builder.message_with_repeated(
        "test.Container",
        {"entries": (T.TYPE_MESSAGE, 1, ".test.Entry")},
        repeated_fields={"entries"},
    )
    return builder


class TestTreatAsMapEqual:
    def test_same_elements_same_order(self) -> None:
        b = _make_items_builder()
        item_cls = b.get_message_class("test.Item")
        msg1 = b.build(
            "test.Container", items=[item_cls(id="a", value=1), item_cls(id="b", value=2)],
        )
        msg2 = b.build(
            "test.Container", items=[item_cls(id="a", value=1), item_cls(id="b", value=2)],
        )
        d = MessageDifferencer()
        d.treat_as_map("items", key="id")
        result = d.compare(msg1, msg2)
        assert not result.has_changes()

    def test_same_elements_different_order(self) -> None:
        """Key-based matching should ignore order."""
        b = _make_items_builder()
        item_cls = b.get_message_class("test.Item")
        msg1 = b.build(
            "test.Container", items=[item_cls(id="a", value=1), item_cls(id="b", value=2)],
        )
        msg2 = b.build(
            "test.Container", items=[item_cls(id="b", value=2), item_cls(id="a", value=1)],
        )
        d = MessageDifferencer()
        d.treat_as_map("items", key="id")
        result = d.compare(msg1, msg2)
        assert not result.has_changes()


class TestTreatAsMapDifferences:
    def test_value_changed(self) -> None:
        b = _make_items_builder()
        item_cls = b.get_message_class("test.Item")
        msg1 = b.build("test.Container", items=[item_cls(id="a", value=1)])
        msg2 = b.build("test.Container", items=[item_cls(id="a", value=2)])
        d = MessageDifferencer()
        d.treat_as_map("items", key="id")
        result = d.compare(msg1, msg2)
        assert result.has_changes()
        diff = result.differences[0]
        assert diff.change_type == ChangeType.MODIFIED
        assert 'id="a"' in str(diff.path)

    def test_element_added(self) -> None:
        b = _make_items_builder()
        item_cls = b.get_message_class("test.Item")
        msg1 = b.build("test.Container", items=[item_cls(id="a", value=1)])
        msg2 = b.build(
            "test.Container", items=[item_cls(id="a", value=1), item_cls(id="b", value=2)],
        )
        d = MessageDifferencer()
        d.treat_as_map("items", key="id")
        result = d.compare(msg1, msg2)
        assert result.has_changes()
        added = [x for x in result if x.change_type == ChangeType.ADDED]
        assert len(added) >= 1

    def test_element_removed(self) -> None:
        b = _make_items_builder()
        item_cls = b.get_message_class("test.Item")
        msg1 = b.build(
            "test.Container", items=[item_cls(id="a", value=1), item_cls(id="b", value=2)],
        )
        msg2 = b.build("test.Container", items=[item_cls(id="a", value=1)])
        d = MessageDifferencer()
        d.treat_as_map("items", key="id")
        result = d.compare(msg1, msg2)
        removed = [x for x in result if x.change_type == ChangeType.REMOVED]
        assert len(removed) >= 1

    def test_int_key(self) -> None:
        b = _make_int_key_builder()
        entry_cls = b.get_message_class("test.Entry")
        msg1 = b.build("test.Container", entries=[entry_cls(key=1, name="one")])
        msg2 = b.build("test.Container", entries=[entry_cls(key=1, name="ONE")])
        d = MessageDifferencer()
        d.treat_as_map("entries", key="key")
        result = d.compare(msg1, msg2)
        assert result.has_changes()
        assert result.differences[0].change_type == ChangeType.MODIFIED


class TestTreatAsMapErrors:
    def test_duplicate_key_raises(self) -> None:
        b = _make_items_builder()
        item_cls = b.get_message_class("test.Item")
        msg1 = b.build(
            "test.Container", items=[item_cls(id="a", value=1), item_cls(id="a", value=2)],
        )
        msg2 = b.build("test.Container", items=[item_cls(id="a", value=1)])
        d = MessageDifferencer()
        d.treat_as_map("items", key="id")
        with pytest.raises(DuplicateKeyError):
            d.compare(msg1, msg2)


    def test_missing_key_raises(self) -> None:
        """Proto2 optional key field that is unset should raise MissingKeyError."""
        builder = ProtoBuilder()
        builder.message("test.Item", {
            "id": (T.TYPE_STRING, 1),
            "value": (T.TYPE_INT32, 2),
        }, syntax="proto2")
        builder.message_with_repeated(
            "test.Container",
            {"items": (T.TYPE_MESSAGE, 1, ".test.Item")},
            repeated_fields={"items"},
            syntax="proto2",
        )
        item_cls = builder.get_message_class("test.Item")
        # Create an element without setting the key field "id"
        msg1 = builder.build("test.Container", items=[item_cls(value=1)])
        msg2 = builder.build("test.Container", items=[item_cls(id="a", value=1)])
        d = MessageDifferencer()
        d.treat_as_map("items", key="id")
        with pytest.raises(MissingKeyError, match="missing key field 'id'"):
            d.compare(msg1, msg2)


class TestTreatAsMapReRegistration:
    """Re-registering a selector must not silently desync the two config stores."""

    def test_conflicting_key_raises(self) -> None:
        d = MessageDifferencer()
        d.treat_as_map("items", key="id")
        with pytest.raises(ValueError, match="already configured with key 'id'"):
            d.treat_as_map("items", key="name")

    def test_conflicting_key_raises_for_dotted_selector(self) -> None:
        d = MessageDifferencer()
        d.treat_as_map("wrapper.items", key="id")
        with pytest.raises(ValueError, match="already configured with key 'id'"):
            d.treat_as_map("wrapper.items", key="name")

    def test_conflicting_key_leaves_ignore_conflict_detection_intact(self) -> None:
        """The rejected key must not become the one the ignore checks consult."""
        d = MessageDifferencer()
        d.treat_as_map("wrapper.items", key="id")
        with pytest.raises(ValueError):
            d.treat_as_map("wrapper.items", key="name")
        # 'id' is still the key in force, so ignoring it must be rejected.
        with pytest.raises(ValueError, match="key field"):
            d.ignore_fields("wrapper.items.id")

    def test_same_key_is_idempotent(self) -> None:
        b = _make_items_builder()
        item_cls = b.get_message_class("test.Item")
        msg1 = b.build(
            "test.Container", items=[item_cls(id="a", value=1), item_cls(id="b", value=2)],
        )
        msg2 = b.build(
            "test.Container", items=[item_cls(id="b", value=2), item_cls(id="a", value=1)],
        )
        d = MessageDifferencer()
        d.treat_as_map("items", key="id")
        d.treat_as_map("items", key="id")
        assert not d.compare(msg1, msg2).has_changes()


class TestTreatAsMapNonMessage:
    def test_non_message_field_emits_warning_and_falls_back(self) -> None:
        """treat_as_map on a repeated scalar should warn and use index comparison."""
        builder = ProtoBuilder()
        builder.message_with_repeated(
            "test.Container",
            {"tags": (T.TYPE_STRING, 1)},
            repeated_fields={"tags"},
        )
        msg1 = builder.build("test.Container", tags=["a", "b"])
        msg2 = builder.build("test.Container", tags=["b", "a"])
        d = MessageDifferencer()
        d.treat_as_map("tags", key="id")
        result = d.compare(msg1, msg2)
        # Should have fallen back to index-based comparison (order matters)
        assert result.has_changes()
        # Should have emitted a warning about non-message field
        assert len(result.warnings) == 1
        expected_warning = "treat_as_map configured but field is not a repeated message"
        assert expected_warning in result.warnings[0].message

    def test_non_message_field_equal_values(self) -> None:
        """treat_as_map on a repeated scalar with equal values should still work."""
        builder = ProtoBuilder()
        builder.message_with_repeated(
            "test.Container",
            {"tags": (T.TYPE_STRING, 1)},
            repeated_fields={"tags"},
        )
        msg1 = builder.build("test.Container", tags=["a", "b"])
        msg2 = builder.build("test.Container", tags=["a", "b"])
        d = MessageDifferencer()
        d.treat_as_map("tags", key="id")
        result = d.compare(msg1, msg2)
        assert not result.has_changes()
        # Warning should still be emitted
        assert len(result.warnings) == 1


class TestTreatAsMapDottedPath:
    def test_dotted_selector_matches_nested_field(self) -> None:
        """treat_as_map("wrapper.items", key="id") should match inside a singular parent."""
        builder = ProtoBuilder()
        builder.message("test.Item", {
            "id": (T.TYPE_STRING, 1),
            "value": (T.TYPE_INT32, 2),
        })
        builder.message_with_repeated(
            "test.Wrapper",
            {
                "name": (T.TYPE_STRING, 1),
                "items": (T.TYPE_MESSAGE, 2, ".test.Item"),
            },
            repeated_fields={"items"},
        )
        builder.message("test.Container", {
            "wrapper": (T.TYPE_MESSAGE, 1, ".test.Wrapper"),
        })
        item_cls = builder.get_message_class("test.Item")
        wrapper_cls = builder.get_message_class("test.Wrapper")
        msg1 = builder.get_message_class("test.Container")(
            wrapper=wrapper_cls(
                name="g1",
                items=[item_cls(id="a", value=1), item_cls(id="b", value=2)],
            )
        )
        msg2 = builder.get_message_class("test.Container")(
            wrapper=wrapper_cls(
                name="g1",
                items=[item_cls(id="b", value=2), item_cls(id="a", value=1)],
            )
        )
        d = MessageDifferencer()
        d.treat_as_map("wrapper.items", key="id")
        result = d.compare(msg1, msg2)
        # Key-based matching should ignore order
        assert not result.has_changes()


class TestTreatAsMapEmitAll:
    def test_added_subtree_uses_key_paths(self) -> None:
        """When an entire sub-message is added, treat_as_map fields inside
        should use key-based paths, not index-based."""
        # Left schema: Outer with just name
        b1 = ProtoBuilder()
        b1.message("test.Outer", {"name": (T.TYPE_STRING, 1)})

        # Right schema: Outer with name + inner (which has repeated items)
        b2 = ProtoBuilder()
        b2.message("test.Item", {
            "id": (T.TYPE_STRING, 1),
            "value": (T.TYPE_INT32, 2),
        })
        b2.message_with_repeated(
            "test.Inner",
            {"items": (T.TYPE_MESSAGE, 1, ".test.Item")},
            repeated_fields={"items"},
        )
        b2.message("test.Outer", {
            "name": (T.TYPE_STRING, 1),
            "inner": (T.TYPE_MESSAGE, 2, ".test.Inner"),
        })
        item_cls = b2.get_message_class("test.Item")
        inner_cls = b2.get_message_class("test.Inner")
        msg1 = b1.build("test.Outer", name="hello")
        msg2 = b2.build("test.Outer",
            name="hello",
            inner=inner_cls(items=[item_cls(id="a", value=1), item_cls(id="b", value=2)]),
        )
        d = MessageDifferencer()
        d.treat_as_map("items", key="id")
        result = d.compare(msg1, msg2)
        # Only ADDED diffs expected for a new subtree
        assert all(x.change_type == ChangeType.ADDED for x in result)
        added = list(result)
        # Paths should use key-based brackets
        paths = [str(x.path) for x in added]
        assert any('id="a"' in p for p in paths)
        assert any('id="b"' in p for p in paths)
        # Should NOT use index-based brackets
        assert not any("items[0]" in p for p in paths)
        assert not any("items[1]" in p for p in paths)


    def test_duplicate_key_in_added_subtree_raises(self) -> None:
        """Key validation must not depend on whether the other side had the
        subtree — two elements would otherwise collapse onto one path."""
        b = ProtoBuilder()
        b.message("test.Item", {
            "id": (T.TYPE_STRING, 1),
            "value": (T.TYPE_INT32, 2),
        })
        b.message_with_repeated(
            "test.Inner",
            {"items": (T.TYPE_MESSAGE, 1, ".test.Item")},
            repeated_fields={"items"},
        )
        b.message("test.Outer", {
            "name": (T.TYPE_STRING, 1),
            "inner": (T.TYPE_MESSAGE, 2, ".test.Inner"),
        })
        item_cls = b.get_message_class("test.Item")
        inner_cls = b.get_message_class("test.Inner")
        msg1 = b.build("test.Outer", name="hello")
        msg2 = b.build("test.Outer",
            name="hello",
            inner=inner_cls(items=[item_cls(id="a", value=1), item_cls(id="a", value=2)]),
        )
        d = MessageDifferencer()
        d.treat_as_map("items", key="id")
        with pytest.raises(DuplicateKeyError, match="Duplicate key 'a' in 'inner.items'"):
            d.compare(msg1, msg2)

    def test_missing_key_in_added_subtree_raises(self) -> None:
        """A proto2 element with an unset key silently fell back to an index
        bracket here, while the two-sided path raises."""
        b = ProtoBuilder()
        b.message("test.Item", {
            "id": (T.TYPE_STRING, 1),
            "value": (T.TYPE_INT32, 2),
        }, syntax="proto2")
        b.message_with_repeated(
            "test.Inner",
            {"items": (T.TYPE_MESSAGE, 1, ".test.Item")},
            repeated_fields={"items"},
            syntax="proto2",
        )
        b.message("test.Outer", {
            "name": (T.TYPE_STRING, 1),
            "inner": (T.TYPE_MESSAGE, 2, ".test.Inner"),
        }, syntax="proto2")
        item_cls = b.get_message_class("test.Item")
        inner_cls = b.get_message_class("test.Inner")
        msg1 = b.build("test.Outer", name="hello")
        msg2 = b.build("test.Outer", name="hello", inner=inner_cls(items=[item_cls(value=1)]))
        d = MessageDifferencer()
        d.treat_as_map("items", key="id")
        with pytest.raises(MissingKeyError, match="missing key field 'id'"):
            d.compare(msg1, msg2)


class TestTreatAsMapPath:
    def test_path_contains_key(self) -> None:
        """The diff path should include the key bracket notation."""
        b = _make_items_builder()
        item_cls = b.get_message_class("test.Item")
        msg1 = b.build("test.Container", items=[item_cls(id="x", value=1)])
        msg2 = b.build("test.Container", items=[item_cls(id="x", value=9)])
        d = MessageDifferencer()
        d.treat_as_map("items", key="id")
        result = d.compare(msg1, msg2)
        path_str = str(result.differences[0].path)
        assert 'id="x"' in path_str


# ---------------------------------------------------------------------------
# 0.17.0: a key field that cannot key the elements (C10-C4, E06-C5)
# ---------------------------------------------------------------------------


def _rows_classes(*, with_rows: bool = True) -> dict[str, type]:
    """``r.Outer { M m }``, ``r.M { repeated Row rows }``, ``Row { s; Inner k; repeated r }``.

    Without ``rows`` the same names are declared but ``M`` holds a ``note``
    instead, so ``rows`` is a field only the other schema has. Built in its own
    pool.
    """
    fp = descriptor_pb2.FileDescriptorProto(name="r.proto", package="r", syntax="proto3")
    inner = fp.message_type.add(name="Inner")
    inner.field.add(name="id", number=1, type=T.TYPE_STRING, label=T.LABEL_OPTIONAL)
    row = fp.message_type.add(name="Row")
    row.field.add(name="s", number=1, type=T.TYPE_STRING, label=T.LABEL_OPTIONAL)
    row.field.add(
        name="k", number=2, type=T.TYPE_MESSAGE, type_name=".r.Inner", label=T.LABEL_OPTIONAL,
    )
    row.field.add(name="r", number=3, type=T.TYPE_INT32, label=T.LABEL_REPEATED)
    m = fp.message_type.add(name="M")
    m.field.add(name="note", number=9, type=T.TYPE_STRING, label=T.LABEL_OPTIONAL)
    if with_rows:
        m.field.add(
            name="rows", number=1, type=T.TYPE_MESSAGE, type_name=".r.Row",
            label=T.LABEL_REPEATED,
        )
    fp.message_type.add(name="Outer").field.add(
        name="m", number=1, type=T.TYPE_MESSAGE, type_name=".r.M", label=T.LABEL_OPTIONAL,
    )
    pool = descriptor_pool.DescriptorPool()
    pool.Add(fp)
    return {
        name: message_factory.GetMessageClass(pool.FindMessageTypeByName(f"r.{name}"))
        for name in ("M", "Outer")
    }


def _with_one_row(cls: type) -> object:
    msg = cls()
    row = msg.rows.add(s="x", r=[1])  # type: ignore[attr-defined]
    row.k.id = "a"
    return msg


_UNUSABLE_KEYS = pytest.mark.parametrize(
    ("key", "reason"),
    [
        ("k", "is a message field"),
        ("r", "is a repeated field"),
        ("nope", "not found"),
    ],
    ids=["message-typed", "repeated", "not-found"],
)


class TestKeyFieldThatCannotKey:
    """A key field that cannot key the elements raises ``InvalidKeyFieldError``.

    The error is a ``ValueError`` naming the field, so ``protokit diff`` exits 2.
    It is raised whatever the elements hold, as a configuration error, and on
    every route a ``treat_as_map`` field takes.
    """

    @_UNUSABLE_KEYS
    @pytest.mark.parametrize("populated", [True, False], ids=["populated", "empty"])
    def test_both_sides_declare_the_field(self, key: str, reason: str, populated: bool) -> None:
        cls = _rows_classes()["M"]
        msg = _with_one_row(cls) if populated else cls()
        d = MessageDifferencer()
        d.treat_as_map("rows", key=key)

        with pytest.raises(InvalidKeyFieldError, match=f"key field '{key}'.*{reason}"):
            d.compare(msg, msg)

    @_UNUSABLE_KEYS
    def test_one_schema_declares_the_field(self, key: str, reason: str) -> None:
        """The field only the left schema has is emitted one-sided, and keyed there too."""
        left = _with_one_row(_rows_classes()["M"])
        right = _rows_classes(with_rows=False)["M"](note="n")
        d = MessageDifferencer()
        d.treat_as_map("rows", key=key)

        with pytest.raises(InvalidKeyFieldError, match=f"key field '{key}'.*{reason}"):
            d.compare(left, right)

    @_UNUSABLE_KEYS
    def test_an_added_subtree_holds_the_field(self, key: str, reason: str) -> None:
        """A whole subtree on one side only: its keyed list is checked as well."""
        outer = _rows_classes()["Outer"]
        right = outer()
        row = right.m.rows.add(s="x", r=[1])  # type: ignore[attr-defined]
        row.k.id = "a"
        d = MessageDifferencer()
        d.treat_as_map("rows", key=key)

        with pytest.raises(InvalidKeyFieldError, match=f"key field '{key}'.*{reason}"):
            d.compare(outer(), right)

    @_UNUSABLE_KEYS
    def test_an_added_subtree_with_an_empty_list_is_checked_too(
        self, key: str, reason: str,
    ) -> None:
        """The one-sided walk sees only populated fields; an empty keyed list is still checked.

        With both parents present, the same empty ``rows`` raises, so the error must not
        depend on whether the other side holds the subtree.
        """
        outer = _rows_classes()["Outer"]
        right = outer()
        right.m.note = "n"  # type: ignore[attr-defined]
        d = MessageDifferencer()
        d.treat_as_map("rows", key=key)

        with pytest.raises(InvalidKeyFieldError, match=f"key field '{key}'.*{reason}"):
            d.compare(outer(), right)

    def test_an_ignored_empty_list_in_an_added_subtree_is_not_checked(self) -> None:
        """An ignored field is not checked, as on the two-sided walk (a predicate can ignore it)."""
        outer = _rows_classes()["Outer"]
        right = outer()
        right.m.note = "n"  # type: ignore[attr-defined]
        d = MessageDifferencer()
        d.treat_as_map("rows", key="k")
        d.ignore_fields(lambda fd, path: fd.name == "rows")

        assert [str(diff.path) for diff in d.compare(outer(), right)] == ["m.note"]

    def test_a_set_pairing_trial_below_the_depth_cut_does_not_raise(self) -> None:
        """Pairing trials have no depth limit; an unusable key below the cut stays unread.

        ``DescriptorProto.field`` keyed on its message-typed ``options`` is unusable, but
        ``max_depth=0`` keeps the walk from reaching it, so the comparison returns. Trying
        ``treat_as_set`` partners for ``message_type`` must not change that.
        """
        msg = descriptor_pb2.FileDescriptorProto(
            message_type=[descriptor_pb2.DescriptorProto(name="A")],
        )
        results = []
        for with_set in (False, True):
            d = MessageDifferencer()
            d.treat_as_map("field", key="options")
            d.max_depth = 0
            if with_set:
                d.treat_as_set("message_type")
            result = d.compare(msg, msg)
            results.append((list(result.differences), {str(p) for p in result.truncated_paths}))

        assert results[0] == results[1] == ([], {"message_type[0]"})

    def test_under_partial_an_empty_list_in_a_removed_subtree_is_not_checked(self) -> None:
        """Partial compares only what the expected side holds, so its empty list is skipped.

        The two-sided walk skips the same empty field under partial.
        """
        outer = _rows_classes()["Outer"]
        left = outer()
        left.m.note = "n"  # type: ignore[attr-defined]
        both = outer()
        both.m.note = "n"  # type: ignore[attr-defined]
        for right in (outer(), both):
            d = MessageDifferencer()
            d.treat_as_map("rows", key="k")
            d.set_partial()
            d.compare(left, right)

    @pytest.mark.xfail(
        strict=True,
        raises=pytest.fail.Exception,
        reason="U14 review (owned by U4, 0.17.0): a message held by one side only that is "
               "entirely empty is reported ADDED or REMOVED without its fields being read, "
               "so an unusable treat_as_map key on a list inside it is not refused, while the "
               "same message on both sides raises InvalidKeyFieldError (0.16.0 behaved the same)",
    )
    def test_an_empty_element_held_by_one_side_still_has_its_key_field_checked(self) -> None:
        file_proto = descriptor_pb2.FileDescriptorProto(
            name="e.proto", package="e", syntax="proto3",
        )
        file_proto.message_type.add(name="E")
        c = file_proto.message_type.add(name="C")
        c.field.add(
            name="items", number=1, type=T.TYPE_MESSAGE, type_name=".e.E", label=T.LABEL_REPEATED,
        )
        file_proto.message_type.add(name="M").field.add(
            name="children", number=1, type=T.TYPE_MESSAGE, type_name=".e.C",
            label=T.LABEL_REPEATED,
        )
        pool = descriptor_pool.DescriptorPool()
        pool.Add(file_proto)
        cls = message_factory.GetMessageClass(pool.FindMessageTypeByName("e.M"))
        left = cls()
        left.children.add()
        d = MessageDifferencer()
        d.treat_as_map("items", key="id")

        with pytest.raises(InvalidKeyFieldError):
            d.compare(left, left)
        with pytest.raises(InvalidKeyFieldError):
            d.compare(left, cls())
