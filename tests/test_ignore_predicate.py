"""Tests for predicate-form (and FieldSelector-form) ``ignore_fields``.

U2: ``MessageDifferencer.ignore_fields`` accepts a
``(FieldDescriptor, FieldPath) -> bool`` predicate (or a pre-built
``FieldSelector``) in addition to the existing bare-name / dotted-path
strings. The predicate is consulted at the SAME selection gate
(``_is_ignored``) as the string forms — there is no new emit-path gate — so
it suppresses modified, added, and removed fields symmetrically.

Each suppression scenario follows the baseline-then-mechanism discipline: first
assert the field DOES produce a Difference with no ignore configured, then
assert the predicate suppresses it (per the documented-solutions guidance on
proving the proxy signal is non-vacuous).
"""

from __future__ import annotations

import pytest
from google.protobuf import descriptor_pb2

from protokit.message import MessageDifferencer
from protokit.message._selector import FieldSelector
from tests.proto_builder import ProtoBuilder

T = descriptor_pb2.FieldDescriptorProto


def _internal_predicate(fd: object, path: object) -> bool:
    """Ignore any field whose name ends in ``_internal``."""
    return fd.name.endswith("_internal")  # type: ignore[attr-defined]


class TestPredicateIgnoreModified:
    """AE3: a name-based predicate ignores matching fields at any depth."""

    def _builder(self) -> ProtoBuilder:
        b = ProtoBuilder()
        b.message(
            "test.Inner",
            {
                "value_internal": (T.TYPE_INT32, 1),
                "label": (T.TYPE_STRING, 2),
            },
        )
        b.message(
            "test.Outer",
            {
                "token_internal": (T.TYPE_STRING, 1),
                "name": (T.TYPE_STRING, 2),
                "inner": (T.TYPE_MESSAGE, 3, ".test.Inner"),
            },
        )
        return b

    def test_baseline_internal_fields_reported(self) -> None:
        b = self._builder()
        inner_cls = b.get_message_class("test.Inner")
        m1 = b.build(
            "test.Outer", token_internal="a", name="N", inner=inner_cls(value_internal=1, label="x")
        )
        m2 = b.build(
            "test.Outer", token_internal="b", name="N", inner=inner_cls(value_internal=2, label="x")
        )
        d = MessageDifferencer()
        result = d.compare(m1, m2)
        paths = {str(diff.path) for diff in result.differences}
        # Without the predicate, both *_internal differences surface.
        assert paths == {"token_internal", "inner.value_internal"}

    def test_predicate_ignores_internal_at_any_depth(self) -> None:
        b = self._builder()
        inner_cls = b.get_message_class("test.Inner")
        m1 = b.build(
            "test.Outer", token_internal="a", name="N", inner=inner_cls(value_internal=1, label="x")
        )
        m2 = b.build(
            "test.Outer", token_internal="b", name="N", inner=inner_cls(value_internal=2, label="x")
        )
        d = MessageDifferencer()
        d.ignore_fields(_internal_predicate)
        result = d.compare(m1, m2)
        # Top-level token_internal AND nested inner.value_internal suppressed.
        assert not result.has_changes()

    def test_predicate_via_fieldselector_object(self) -> None:
        """A pre-built FieldSelector (predicate form) is accepted as-is."""
        b = self._builder()
        inner_cls = b.get_message_class("test.Inner")
        m1 = b.build(
            "test.Outer", token_internal="a", name="N", inner=inner_cls(value_internal=1, label="x")
        )
        m2 = b.build(
            "test.Outer", token_internal="b", name="N", inner=inner_cls(value_internal=2, label="x")
        )
        d = MessageDifferencer()
        d.ignore_fields(FieldSelector.of(_internal_predicate))
        result = d.compare(m1, m2)
        assert not result.has_changes()

    def test_lambda_predicate(self) -> None:
        b = self._builder()
        inner_cls = b.get_message_class("test.Inner")
        m1 = b.build(
            "test.Outer", token_internal="a", name="N", inner=inner_cls(value_internal=1, label="x")
        )
        m2 = b.build(
            "test.Outer", token_internal="b", name="N", inner=inner_cls(value_internal=2, label="x")
        )
        d = MessageDifferencer()
        d.ignore_fields(lambda fd, path: fd.name.endswith("_internal"))
        result = d.compare(m1, m2)
        assert not result.has_changes()

    def test_non_matching_field_still_reported(self) -> None:
        """A predicate that ignores *_internal leaves a real diff intact."""
        b = self._builder()
        inner_cls = b.get_message_class("test.Inner")
        m1 = b.build("test.Outer", token_internal="a", name="A", inner=inner_cls(label="x"))
        m2 = b.build("test.Outer", token_internal="b", name="B", inner=inner_cls(label="x"))
        d = MessageDifferencer()
        d.ignore_fields(_internal_predicate)
        result = d.compare(m1, m2)
        assert len(result) == 1
        assert str(result.differences[0].path) == "name"


class TestPredicateIgnoreAddedRemoved:
    """Predicate ignore routes through the existing gate -> covers one-sided.

    A sub-message set on one side only is emitted leaf-by-leaf through
    ``_emit_all_fields`` (ADDED/REMOVED). That is the gate site the predicate
    now consults; no new emit-path change is needed.
    """

    def _builder(self) -> ProtoBuilder:
        b = ProtoBuilder()
        b.message(
            "test.Inner",
            {
                "value_internal": (T.TYPE_INT32, 1),
                "keep": (T.TYPE_INT32, 2),
            },
        )
        b.message(
            "test.Outer",
            {
                "inner": (T.TYPE_MESSAGE, 1, ".test.Inner"),
                "name": (T.TYPE_STRING, 2),
            },
        )
        return b

    def test_baseline_removed_internal_reported(self) -> None:
        b = self._builder()
        inner_cls = b.get_message_class("test.Inner")
        # inner set on left only -> its leaves are REMOVED.
        m1 = b.build("test.Outer", name="N", inner=inner_cls(value_internal=7, keep=1))
        m2 = b.build("test.Outer", name="N")
        d = MessageDifferencer()
        result = d.compare(m1, m2)
        paths = {str(diff.path) for diff in result.differences}
        assert paths == {"inner.value_internal", "inner.keep"}

    def test_predicate_suppresses_removed_field(self) -> None:
        b = self._builder()
        inner_cls = b.get_message_class("test.Inner")
        m1 = b.build("test.Outer", name="N", inner=inner_cls(value_internal=7, keep=1))
        m2 = b.build("test.Outer", name="N")
        d = MessageDifferencer()
        d.ignore_fields(_internal_predicate)
        result = d.compare(m1, m2)
        # The *_internal leaf is suppressed even though it is REMOVED; the
        # sibling "keep" (not matched by the predicate) still surfaces.
        paths = {str(diff.path) for diff in result.differences}
        assert paths == {"inner.keep"}

    def test_baseline_added_internal_reported(self) -> None:
        b = self._builder()
        inner_cls = b.get_message_class("test.Inner")
        # inner set on right only -> its leaves are ADDED.
        m1 = b.build("test.Outer", name="N")
        m2 = b.build("test.Outer", name="N", inner=inner_cls(value_internal=9, keep=2))
        d = MessageDifferencer()
        result = d.compare(m1, m2)
        paths = {str(diff.path) for diff in result.differences}
        assert paths == {"inner.value_internal", "inner.keep"}

    def test_predicate_suppresses_added_field(self) -> None:
        b = self._builder()
        inner_cls = b.get_message_class("test.Inner")
        m1 = b.build("test.Outer", name="N")
        m2 = b.build("test.Outer", name="N", inner=inner_cls(value_internal=9, keep=2))
        d = MessageDifferencer()
        d.ignore_fields(_internal_predicate)
        result = d.compare(m1, m2)
        paths = {str(diff.path) for diff in result.differences}
        assert paths == {"inner.keep"}


class TestPredicateIgnoreOneSidedSchema:
    """A field present in only one *schema* (cross-pool) is also gated.

    The top-level pre-dispatch gate now passes the available descriptor, so a
    predicate can suppress a field that exists on only one side's descriptor.
    """

    def test_predicate_suppresses_schema_only_field(self) -> None:
        b1 = ProtoBuilder()
        b1.message(
            "test.M",
            {
                "shared": (T.TYPE_INT32, 1),
                "extra_internal": (T.TYPE_INT32, 2),
            },
        )
        b2 = ProtoBuilder()
        b2.message("test.M", {"shared": (T.TYPE_INT32, 1)})
        m1 = b1.build("test.M", shared=1, extra_internal=42)
        m2 = b2.build("test.M", shared=1)

        # Baseline: extra_internal exists only on left's schema -> REMOVED.
        d0 = MessageDifferencer()
        base = d0.compare(m1, m2)
        assert {str(x.path) for x in base.differences} == {"extra_internal"}

        # Predicate suppresses it at the pre-dispatch gate.
        d = MessageDifferencer()
        d.ignore_fields(_internal_predicate)
        result = d.compare(m1, m2)
        assert not result.has_changes()


class TestPredicatePathReceivesDescriptorAndPath:
    """KTD-10: the predicate receives (FieldDescriptor, FieldPath) explicitly."""

    def test_predicate_args_are_descriptor_and_path(self) -> None:
        b = ProtoBuilder()
        b.message("test.M", {"alpha": (T.TYPE_INT32, 1), "beta": (T.TYPE_INT32, 2)})
        m1 = b.build("test.M", alpha=1, beta=2)
        m2 = b.build("test.M", alpha=10, beta=20)

        recorded: list[tuple[str, str]] = []

        def record(fd: object, path: object) -> bool:
            # fd is a FieldDescriptor (has .name); path stringifies to the path.
            recorded.append((fd.name, str(path)))  # type: ignore[attr-defined]
            return fd.name == "alpha"  # type: ignore[attr-defined]

        d = MessageDifferencer()
        d.ignore_fields(record)
        result = d.compare(m1, m2)

        # alpha was ignored; beta surfaces.
        assert {str(x.path) for x in result.differences} == {"beta"}
        # The predicate saw both fields with descriptor name == path here.
        assert ("alpha", "alpha") in recorded
        assert ("beta", "beta") in recorded


class TestStringFormUnchanged:
    """Regression: bare-name and dotted-path ignore behavior is byte-identical."""

    def test_bare_name_still_ignores_globally(self) -> None:
        b = ProtoBuilder()
        b.message("test.Inner", {"name": (T.TYPE_STRING, 1), "score": (T.TYPE_INT32, 2)})
        b.message(
            "test.Outer",
            {"name": (T.TYPE_STRING, 1), "inner": (T.TYPE_MESSAGE, 2, ".test.Inner")},
        )
        inner_cls = b.get_message_class("test.Inner")
        m1 = b.build("test.Outer", name="A", inner=inner_cls(name="X", score=1))
        m2 = b.build("test.Outer", name="B", inner=inner_cls(name="Y", score=1))
        d = MessageDifferencer()
        d.ignore_fields("name")
        assert not d.compare(m1, m2).has_changes()

    def test_dotted_path_still_scoped(self) -> None:
        b = ProtoBuilder()
        b.message("test.Inner", {"name": (T.TYPE_STRING, 1)})
        b.message(
            "test.Outer",
            {"name": (T.TYPE_STRING, 1), "inner": (T.TYPE_MESSAGE, 2, ".test.Inner")},
        )
        inner_cls = b.get_message_class("test.Inner")
        m1 = b.build("test.Outer", name="A", inner=inner_cls(name="X"))
        m2 = b.build("test.Outer", name="B", inner=inner_cls(name="Y"))
        d = MessageDifferencer()
        d.ignore_fields("inner.name")
        result = d.compare(m1, m2)
        assert len(result) == 1
        assert str(result.differences[0].path) == "name"

    def test_mixed_string_and_predicate_in_one_call(self) -> None:
        """Strings and a predicate can be mixed in a single ignore_fields call."""
        b = ProtoBuilder()
        b.message(
            "test.M",
            {
                "id": (T.TYPE_INT32, 1),
                "name": (T.TYPE_STRING, 2),
                "audit_internal": (T.TYPE_INT32, 3),
            },
        )
        m1 = b.build("test.M", id=1, name="a", audit_internal=5)
        m2 = b.build("test.M", id=2, name="b", audit_internal=6)
        d = MessageDifferencer()
        d.ignore_fields("name", _internal_predicate)
        result = d.compare(m1, m2)
        # name (string) and audit_internal (predicate) suppressed; id remains.
        assert {str(x.path) for x in result.differences} == {"id"}


class TestTreatAsMapConflictStillRaises:
    """The string/path vs treat_as_map conflict still raises at registration.

    A predicate-form ignore is NOT conflict-checked at registration (opaque
    callable); registering one against a treat_as_map field does not raise.
    """

    def _map_differ(self) -> MessageDifferencer:
        d = MessageDifferencer()
        d.treat_as_map("items", key="id")
        return d

    def test_string_ignore_of_map_field_raises(self) -> None:
        d = self._map_differ()
        with pytest.raises(ValueError, match="treat_as_map"):
            d.ignore_fields("items")

    def test_string_ignore_of_map_key_raises(self) -> None:
        d = self._map_differ()
        with pytest.raises(ValueError, match="key field"):
            d.ignore_fields("id")

    def test_predicate_ignore_not_conflict_checked_at_registration(self) -> None:
        """A predicate overlapping a treat_as_map field registers silently.

        Compare-time behavior is documented as "ignore wins"; registration of
        an opaque predicate cannot and does not raise.
        """
        d = self._map_differ()
        # Must NOT raise even though this predicate would match the map field.
        d.ignore_fields(lambda fd, path: fd.name == "items")


class TestRaisingPredicatePropagates:
    """KTD-10 / SWI-3: a predicate exception propagates, never a diagnostic."""

    def test_predicate_exception_propagates(self) -> None:
        b = ProtoBuilder()
        b.message("test.M", {"a": (T.TYPE_INT32, 1)})
        m1 = b.build("test.M", a=1)
        m2 = b.build("test.M", a=2)

        class BoomError(Exception):
            pass

        def boom(fd: object, path: object) -> bool:
            raise BoomError("predicate exploded")

        d = MessageDifferencer()
        d.ignore_fields(boom)
        with pytest.raises(BoomError, match="predicate exploded"):
            d.compare(m1, m2)
