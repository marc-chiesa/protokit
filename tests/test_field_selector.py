"""Tests for the unified FieldSelector (U1).

Covers both selector forms (dotted-path/bare-name and predicate), the
bracket-blind exact-length path semantics, predicate-exception propagation,
and a semantics-equivalence regression pinning that the path form,
``MessageDifferencer._is_ignored``, and ``_get_treat_as_map_key`` agree on the
same selector/path pair.
"""

from __future__ import annotations

import pytest
from google.protobuf import descriptor as proto_descriptor
from google.protobuf import descriptor_pb2

from protokit.message import MessageDifferencer
from protokit.message._selector import FieldSelector, should_visit
from protokit.message.model import FieldPath
from tests.proto_builder import ProtoBuilder

T = descriptor_pb2.FieldDescriptorProto


def _field(full_name: str, field_name: str) -> proto_descriptor.FieldDescriptor:
    """Resolve a concrete FieldDescriptor for use as the predicate's first arg."""
    builder = ProtoBuilder()
    builder.message(
        full_name,
        {
            "id": (T.TYPE_INT32, 1),
            "name": (T.TYPE_STRING, 2),
            "name_internal": (T.TYPE_STRING, 3),
        },
    )
    desc = builder.pool.FindMessageTypeByName(full_name)
    return desc.fields_by_name[field_name]


# ---------------------------------------------------------------------------
# Path form
# ---------------------------------------------------------------------------


class TestPathForm:
    def test_bare_name_matches_at_any_depth(self) -> None:
        sel = FieldSelector.of("name")
        fd = _field("test.Msg", "name")
        assert sel.matches(fd, FieldPath.parse("name"))
        assert sel.matches(fd, FieldPath.parse("inner.name")) is False  # length differs
        # Bare name matches the single-segment path at any concrete location,
        # bracket-blind: a repeated element's own segment still matches.
        assert sel.matches(fd, FieldPath.parse("name"))

    def test_bare_name_is_bracket_blind(self) -> None:
        sel = FieldSelector.of("items")
        fd = _field("test.Msg", "name")
        assert sel.matches(fd, FieldPath.parse("items[3]"))

    def test_dotted_path_is_scoped(self) -> None:
        sel = FieldSelector.of("inner.name")
        fd = _field("test.Msg", "name")
        assert sel.matches(fd, FieldPath.parse("inner.name"))
        # Same trailing name but different scope: not a match.
        assert sel.matches(fd, FieldPath.parse("outer.name")) is False
        # Bare "name" is one segment, not two: not a match.
        assert sel.matches(fd, FieldPath.parse("name")) is False

    def test_exact_length_bracket_blind_rule(self) -> None:
        """'items.name' matches 'items[0].name' but NOT 'a.items.name'."""
        sel = FieldSelector.of("items.name")
        fd = _field("test.Msg", "name")
        assert sel.matches(fd, FieldPath.parse("items[0].name"))
        assert sel.matches(fd, FieldPath.parse("items.name"))
        # Extra leading segment -> length differs -> no match.
        assert sel.matches(fd, FieldPath.parse("a.items.name")) is False

    def test_non_match_returns_false(self) -> None:
        sel = FieldSelector.of("name")
        fd = _field("test.Msg", "name")
        assert sel.matches(fd, FieldPath.parse("id")) is False

    def test_bracketed_selector_string_is_bracket_blind(self) -> None:
        # FieldPath.parse accepts bracket syntax (bracket rejection lives in the
        # engine's ignore_fields boundary, not the parser). Because the shared
        # matcher is bracket-blind, a bracketed selector behaves identically to
        # its bracket-free form.
        fd = _field("test.Msg", "name")
        bracketed = FieldSelector.of("items[0].name")
        plain = FieldSelector.of("items.name")
        for path_str in ("items[3].name", "items.name"):
            path = FieldPath.parse(path_str)
            assert bracketed.matches(fd, path) == plain.matches(fd, path) is True
        no_match = FieldPath.parse("a.items.name")
        assert bracketed.matches(fd, no_match) == plain.matches(fd, no_match) is False


# ---------------------------------------------------------------------------
# Predicate form
# ---------------------------------------------------------------------------


class _RecordingPredicate:
    """Predicate stub that records the (fd, path) it was called with."""

    def __init__(self, result: bool) -> None:
        self.result = result
        self.calls: list[tuple[proto_descriptor.FieldDescriptor, FieldPath]] = []

    def __call__(
        self, fd: proto_descriptor.FieldDescriptor, path: FieldPath
    ) -> bool:
        self.calls.append((fd, path))
        return self.result


class TestPredicateForm:
    def test_predicate_over_name_selects(self) -> None:
        sel = FieldSelector.of(lambda fd, path: fd.name.endswith("_internal"))
        internal = _field("test.Msg", "name_internal")
        plain = _field("test.Msg", "name")
        assert sel.matches(internal, FieldPath.parse("name_internal"))
        assert sel.matches(plain, FieldPath.parse("name")) is False

    def test_predicate_over_type_selects(self) -> None:
        sel = FieldSelector.of(lambda fd, path: fd.type == T.TYPE_STRING)
        string_fd = _field("test.Msg", "name")
        int_fd = _field("test.Msg", "id")
        assert sel.matches(string_fd, FieldPath.parse("name"))
        assert sel.matches(int_fd, FieldPath.parse("id")) is False

    def test_predicate_over_path_selects(self) -> None:
        sel = FieldSelector.of(
            lambda fd, path: str(path).startswith("inner.")
        )
        fd = _field("test.Msg", "name")
        assert sel.matches(fd, FieldPath.parse("inner.name"))
        assert sel.matches(fd, FieldPath.parse("name")) is False

    def test_predicate_receives_descriptor_and_path(self) -> None:
        stub = _RecordingPredicate(result=True)
        sel = FieldSelector.of(stub)
        fd = _field("test.Msg", "name")
        path = FieldPath.parse("inner.name")
        assert sel.matches(fd, path) is True
        assert len(stub.calls) == 1
        recorded_fd, recorded_path = stub.calls[0]
        assert recorded_fd is fd
        assert recorded_path is path

    def test_predicate_exception_propagates(self) -> None:
        def boom(
            fd: proto_descriptor.FieldDescriptor, path: FieldPath
        ) -> bool:
            raise RuntimeError("author bug")

        sel = FieldSelector.of(boom)
        fd = _field("test.Msg", "name")
        with pytest.raises(RuntimeError, match="author bug"):
            sel.matches(fd, FieldPath.parse("name"))

    def test_is_predicate_flag(self) -> None:
        assert FieldSelector.of(lambda fd, path: True).is_predicate is True
        assert FieldSelector.of("name").is_predicate is False


# ---------------------------------------------------------------------------
# Constructor / normalizer
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_of_passes_through_existing_selector(self) -> None:
        sel = FieldSelector.of("name")
        assert FieldSelector.of(sel) is sel

    def test_of_rejects_bad_type(self) -> None:
        with pytest.raises(TypeError):
            FieldSelector.of(42)  # type: ignore[arg-type]

    def test_requires_exactly_one_form(self) -> None:
        with pytest.raises(ValueError):
            FieldSelector()
        with pytest.raises(ValueError):
            FieldSelector(
                path=FieldPath.parse("name"),
                predicate=lambda fd, path: True,
            )

    def test_path_and_predicate_select_same_target(self) -> None:
        """AE4: the same target is selected by a path and an equivalent predicate."""
        fd = _field("test.Msg", "name")
        path = FieldPath.parse("inner.name")
        path_sel = FieldSelector.of("inner.name")
        pred_sel = FieldSelector.of(
            lambda d, p: list(s.name for s in p.segments) == ["inner", "name"]
        )
        assert path_sel.matches(fd, path) == pred_sel.matches(fd, path) is True
        other = FieldPath.parse("name")
        assert path_sel.matches(fd, other) == pred_sel.matches(fd, other) is False


# ---------------------------------------------------------------------------
# Partial should_visit predicate (co-located, U4 will wire it)
# ---------------------------------------------------------------------------


class TestShouldVisit:
    def test_visits_when_expected_present(self) -> None:
        fd = _field("test.Msg", "name")
        assert should_visit(fd, FieldPath.parse("name"), expected_side_present=True)

    def test_skips_when_expected_absent(self) -> None:
        fd = _field("test.Msg", "name")
        assert (
            should_visit(fd, FieldPath.parse("name"), expected_side_present=False)
            is False
        )


# ---------------------------------------------------------------------------
# Semantics-equivalence regression (KTD-1)
# ---------------------------------------------------------------------------


class TestSemanticsEquivalence:
    """The path-form selector agrees with the engine gates on the same pair.

    Pins the KTD-1 risk: ``FieldSelector`` (path form), ``_is_ignored``, and
    ``_get_treat_as_map_key`` all use the one shared bracket-blind exact-length
    matcher (``FieldPath.matches_selector``), so they must agree exactly.
    """

    def _make_differ(self) -> MessageDifferencer:
        d = MessageDifferencer()
        # Dotted selectors exercise the engine's PATH branches
        # (``_ignore_paths`` / ``_treat_as_map_paths``) — the gate the shared
        # bracket-blind exact-length matcher backs. (A BARE-name selector takes
        # the engine's separate name-set membership branch, which is U2's
        # concern, not the U1 path matcher under test here.)
        d.ignore_fields("items.note")
        d.treat_as_map("data.items", key="id")
        return d

    @pytest.mark.parametrize(
        ("selector_str", "path_str", "expected"),
        [
            # Bracket-blind exact-length: matches concrete bracketed paths...
            ("items.note", "items[0].note", True),
            ("items.note", "items.note", True),
            # ...but is exact-length, so a longer path does NOT match.
            ("items.note", "a.items.note", False),
            # Trailing-name-only is insufficient; the scope must match too.
            ("items.note", "other.note", False),
            ("items", "items[2]", True),
            ("items", "items", True),
            ("items", "a.items", False),
        ],
    )
    def test_selector_matches_engine_ignore_gate(
        self, selector_str: str, path_str: str, expected: bool
    ) -> None:
        d = self._make_differ()
        path = FieldPath.parse(path_str)
        # The engine's ignore gate, for the dotted "items.note" selector.
        ignore_path = FieldPath.parse("items.note")
        engine_ignore = ignore_path.matches_selector(path)

        sel = FieldSelector.of(selector_str)
        last_name = path.segments[-1].name if path.segments else ""
        selector_match = sel.matches(_field("test.Msg", "name"), path)

        # The FieldSelector path-form result is exactly the bracket-blind
        # exact-length match for its own selector string.
        assert selector_match == FieldPath.parse(selector_str).matches_selector(path)
        # And for the matching selector string, it agrees with the engine's gate.
        if selector_str == "items.note":
            assert selector_match == engine_ignore
            # Cross-check the engine's private gate directly too.
            assert d._is_ignored(last_name, path) == selector_match
        assert selector_match is expected

    @pytest.mark.parametrize(
        ("path_str", "is_map_field"),
        [
            ("data.items[0]", True),  # bracket-blind, exact-length
            ("data.items", True),
            ("a.data.items", False),  # length differs -> not the map field
            ("data.other", False),  # trailing name differs
            ("items", False),  # scope differs (length 1, not 2)
        ],
    )
    def test_selector_matches_engine_treat_as_map_gate(
        self, path_str: str, is_map_field: bool
    ) -> None:
        d = self._make_differ()
        path = FieldPath.parse(path_str)
        last_name = path.segments[-1].name if path.segments else ""

        sel = FieldSelector.of("data.items")
        selector_match = sel.matches(_field("test.Msg", "name"), path)

        engine_key = d._get_treat_as_map_key(last_name, path)
        engine_match = engine_key is not None
        assert selector_match == engine_match
        assert selector_match is is_map_field
