"""Tests for the unified FieldSelector (U1).

Covers both selector forms (dotted-path/bare-name and predicate), the
bracket-blind exact-length path semantics, predicate-exception propagation,
and a semantics-equivalence regression pinning that the path form,
``MessageDifferencer._is_ignored``, and ``_get_treat_as_map_key`` agree on the
same selector/path pair.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from google.protobuf import descriptor as proto_descriptor
from google.protobuf import descriptor_pb2

from protokit.message import FloatComparison, MessageDifferencer
from protokit.message._selector import FieldSelector
from protokit.message.matchers import Approx, MatchPolicy
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
        """A bare name selects the field wherever it sits, as ``ignore_fields("name")`` does."""
        sel = FieldSelector.of("name")
        fd = _field("test.Msg", "name")
        assert sel.matches(fd, FieldPath.parse("name"))
        assert sel.matches(fd, FieldPath.parse("inner.name"))
        assert sel.matches(fd, FieldPath.parse("a[0].inner.name"))
        # It names the LAST segment: a path that only passes through ``name``
        # selects a field below it, not ``name``.
        assert sel.matches(fd, FieldPath.parse("name.inner")) is False

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

    @pytest.mark.parametrize("name", ["a.b", "", "foo-bar"])
    def test_a_path_whose_text_means_another_path_is_refused(self, name: str) -> None:
        """A path-form selector registers as its text, so the text must parse to the same path."""
        from protokit.message.model import PathSegment

        with pytest.raises(ValueError, match="does not parse back"):
            FieldSelector(path=FieldPath(segments=(PathSegment(name=name),)))

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
# Semantics-equivalence regression (KTD-1)
# ---------------------------------------------------------------------------


class TestSemanticsEquivalence:
    """The path-form selector agrees with the engine gates on the same pair.

    Pins the KTD-1 risk: ``FieldSelector`` (path form), ``_is_ignored``, and
    ``_get_treat_as_map_key`` all apply the same bracket-blind exact-length
    matching to a dotted path, and all apply a lone extension name
    ``(pkg.ext)`` at any depth, so they must agree on each row's expected value.
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
            # A bare name selects the field at any depth.
            ("items", "a.items", True),
            ("items", "a[1].items[0]", True),
            ("items", "items.a", False),
            # A lone extension name selects that extension at any depth,
            # bracket-blind, and nothing else.
            ("(e.ival)", "(e.ival)", True),
            ("(e.ival)", "inner.(e.ival)", True),
            ("(e.itags)", "a.inner.(e.itags)[3]", True),
            ("(e.ival)", "inner.ival", False),
            ("(e.ival)", "inner.(e.other)", False),
            # A qualified extension path stays exact-length.
            ("inner.(e.ival)", "outer.inner.(e.ival)", False),
        ],
    )
    def test_selector_matches_engine_ignore_gate(
        self, selector_str: str, path_str: str, expected: bool
    ) -> None:
        path = FieldPath.parse(path_str)
        selector_match = FieldSelector.of(selector_str).matches(_field("test.Msg", "name"), path)
        assert selector_match is expected

        # The engine's string ignore gate, configured with the same selector,
        # agrees on every row, bare names included (audit finding V12).
        d = MessageDifferencer()
        d.ignore_fields(selector_str)
        assert d._is_ignored(path.segments[-1].name, path) is expected

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


# ---------------------------------------------------------------------------
# One selector meaning across spellings and policies (R1, KTD1, KTD2)
# ---------------------------------------------------------------------------


def _depths_builder() -> ProtoBuilder:
    """``A { name, B b }``, ``B { name, C c }``, ``C { name }``: ``name`` at depths 0, 1, 2."""
    b = ProtoBuilder()
    b.message("test.C", {"name": (T.TYPE_STRING, 1)})
    b.message("test.B", {"name": (T.TYPE_STRING, 1), "c": (T.TYPE_MESSAGE, 2, ".test.C")})
    b.message("test.A", {"name": (T.TYPE_STRING, 1), "b": (T.TYPE_MESSAGE, 2, ".test.B")})
    return b


class TestBareNameMeansTheSameInEverySpelling:
    """R1: a bare name selects the same fields as a string and as a ``FieldSelector``."""

    @pytest.mark.parametrize(
        "names",
        [
            pytest.param(("a", "b", "c"), id="every-depth-differs"),
            pytest.param(("a", None, None), id="depth-0-only"),
            pytest.param((None, "b", None), id="depth-1-only"),
            pytest.param((None, None, "c"), id="depth-2-only"),
        ],
    )
    def test_string_and_field_selector_ignore_give_identical_results(
        self, names: tuple[str | None, str | None, str | None]
    ) -> None:
        b = _depths_builder()
        c_cls, b_cls = b.get_message_class("test.C"), b.get_message_class("test.B")

        def build(suffix: str) -> object:
            top, mid, low = (None if n is None else n + suffix for n in names)
            inner = b_cls(name=mid or "", c=c_cls(name=low or ""))
            return b.build("test.A", name=top or "", b=inner)

        left, right = build("1"), build("2")
        by_string, by_object = MessageDifferencer(), MessageDifferencer()
        by_string.ignore_fields("name")
        by_object.ignore_fields(FieldSelector.of("name"))

        assert MessageDifferencer().compare(left, right).has_changes()
        assert by_object.compare(left, right) == by_string.compare(left, right)
        assert not by_string.compare(left, right).has_changes()


class TestEmptySelectorIsRefused:
    """An empty selector parses to the root path, which selects everything: refused."""

    @pytest.mark.parametrize(
        "register",
        [
            pytest.param(lambda: FieldSelector.of(""), id="FieldSelector.of"),
            pytest.param(lambda: FieldSelector(path=FieldPath(segments=())), id="path-keyword"),
            pytest.param(lambda: MessageDifferencer().ignore_fields(""), id="ignore_fields"),
            pytest.param(lambda: MessageDifferencer().treat_as_set(""), id="treat_as_set"),
            pytest.param(
                lambda: MessageDifferencer().treat_as_map("", key="id"), id="treat_as_map",
            ),
            pytest.param(
                lambda: MessageDifferencer().set_float_comparison(
                    FloatComparison.APPROXIMATE, fraction=1e-3, selector="",
                ),
                id="float-overlay",
            ),
        ],
    )
    def test_every_entry_point_refuses_it(self, register: Callable[[], object]) -> None:
        with pytest.raises(ValueError, match="empty"):
            register()

    def test_an_empty_str_subclass_whose_bool_lies_is_refused(self) -> None:
        """The check counts the parsed path's segments, not the text's truthiness."""

        class TruthyEmpty(str):
            def __bool__(self) -> bool:
                return True

        with pytest.raises(ValueError, match="empty"):
            FieldSelector.of(TruthyEmpty(""))

    def test_a_bracket_is_reported_as_one_even_when_its_key_is_malformed(self) -> None:
        with pytest.raises(ValueError, match="Bracket syntax is not supported"):
            MessageDifferencer().treat_as_map("items[env]", key="id")


class TestMatchPolicyValidatesItsSelectors:
    """``MatchPolicy`` refuses a selector at construction, not at the first match."""

    @pytest.mark.parametrize(
        "kwargs",
        [
            pytest.param({"as_set": ("items[0]",)}, id="as_set-bracket"),
            pytest.param({"ignore": ("items[0].name",)}, id="ignore-bracket"),
            pytest.param({"ignore": ("",)}, id="ignore-empty"),
            pytest.param(
                {"approx_overlays": (("ratios[0]", Approx(fraction=1e-3)),)}, id="overlay",
            ),
        ],
    )
    def test_construction_raises(self, kwargs: dict[str, object]) -> None:
        with pytest.raises(ValueError):
            MatchPolicy(**kwargs)  # type: ignore[arg-type]

    def test_valid_selectors_construct(self) -> None:
        policy = MatchPolicy(as_set=("items",), ignore=(FieldSelector.of("a.b"),))

        assert policy.as_set == ("items",)


class TestIgnoreBesideASetPolicy:
    """KTD2: an ignore beside another policy on the same field keeps "ignore wins".

    The map-against-map and ignore-against-map conflicts follow the same path
    rule and live with their extension siblings in ``test_extensions.py``.
    """

    @pytest.mark.parametrize("ignore_first", [True, False], ids=["ignore-first", "set-first"])
    def test_ignore_and_set_on_one_field_register_and_the_ignore_wins(
        self, ignore_first: bool
    ) -> None:
        b = ProtoBuilder()
        b.message("test.Inner", {"items": (T.TYPE_STRING, 1)}, repeated_fields={"items"})
        b.message("test.Outer", {"outer": (T.TYPE_MESSAGE, 1, ".test.Inner")})
        inner = b.get_message_class("test.Inner")
        left = b.build("test.Outer", outer=inner(items=["a", "b"]))
        right = b.build("test.Outer", outer=inner(items=["c"]))

        d = MessageDifferencer()
        if ignore_first:
            d.ignore_fields("items")
            d.treat_as_set("outer.items")
        else:
            d.treat_as_set("outer.items")
            d.ignore_fields("items")

        assert not d.compare(left, right).has_changes()
