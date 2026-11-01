"""Regression tests for the message-selector audit findings (family V), closed in 0.17.0.

Each test below began as a strict ``xfail`` pinning a live defect. The
findings are defined in ``docs/plans/AUDIT-whole-codebase-2026-08-30.md`` and
were reproduced again by the cycle-1 re-audit
(``docs/plans/AUDIT-cycle-1-2026-09-27.md``, rows R05-C2, R10-C1 and R10-C2),
and all were owned by unit U9 ("Selector unification") of the stability
release plan. 0.17.0 fixed them, so the markers are gone and the node IDs are
unchanged: each test asserts the correct outcome and fails if it regresses.
The ``# 0.16.0:`` comments record what each one observed before the fix.

Each test asserts the correct outcome, not "something changed". Green control
tests sit beside them and share their construction: they show the harness
reaches the comparison and that the outcome is specific to the mechanism.

Covered here:

* **V8** — ``FieldPath.parse`` stores whatever sits between ``[`` and ``]`` as
  the segment's bracket without checking it against the bracket grammar
  ``model.py`` declares (signed integer, ``true``/``false``, quoted string,
  ``name=value``), so ``items[]``, ``items[+1]``, ``items[TRUE]`` and
  ``items[id=]`` parse although ``parse`` documents ``ValueError`` for a
  malformed path. ``FieldPath.child`` likewise accepts a name that is not one
  grammar name, so ``child("a.b")`` builds ONE segment that renders as ``a.b``
  and parses back as TWO.
* **V12** — a plain bare field name means different things under different
  policies. Given to ``ignore_fields`` or ``treat_as_map`` as a string it
  applies at every depth. Given to ``FieldSelector.of``, ``treat_as_set`` or
  ``set_float_comparison(selector=)`` it matches by exact segment count, which
  for one segment is the top level only. The pins use a PLAIN name on purpose:
  0.16.0 gave the parenthesised extension spelling ``(pkg.ext)`` any-depth
  matching under every policy, and that spelling is covered by ordinary tests
  in ``test_extensions.py``.
* **V13** — the string form of ``ignore_fields`` rejects bracket syntax, but
  ``FieldSelector`` construction, ``treat_as_set`` and
  ``set_float_comparison(selector=)`` accept ``ratios[0]``. Path matching
  ignores brackets, so the accepted selector applies to EVERY element: the
  caller named one element and silently got all of them.
  ``test_field_selector.py`` documents the acceptance as current behaviour
  (``test_bracketed_selector_is_accepted_and_bracket_blind_current_behaviour``);
  that test goes red with these pins' fix and is deleted in the same change.
* **C19-C1** (cycle-1 row R12-C1), with **C19-C1b**'s reach — ``format_key``
  escapes only ``\\`` and ``"`` when it writes a string map key into a path
  bracket, so a newline, a carriage return or an ESC in the key reaches the
  rendered path raw: one difference prints as several lines in the human
  report and in the JUnit failure body, and ESC reaches a terminal. C19-C1b
  is the same key under a message extension and under a proto2 group, which
  0.16.0 began to walk. Found by the second 0.16.0 re-audit and owned by U9
  (0.17.0), because how a key is spelled in a path is the path grammar V8 is
  about.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from collections.abc import Callable

import click
import pytest
from google.protobuf import descriptor_pb2, descriptor_pool, message_factory, text_format
from google.protobuf.message import Message

from protokit.formatters import FormatterContext, FormatterKind, get_formatter
from protokit.message import DiffResult, FloatComparison, MessageDifferencer
from protokit.message._selector import FieldSelector
from protokit.message.model import FieldPath
from tests.proto_builder import ProtoBuilder

T = descriptor_pb2.FieldDescriptorProto


def _observed(result: DiffResult) -> list[tuple[str, str]]:
    """The result's differences as ``(path, change type name)`` pairs."""
    return [(str(diff.path), diff.change_type.name) for diff in result]


# ---------------------------------------------------------------------------
# V8 — FieldPath does not enforce its documented bracket grammar
# ---------------------------------------------------------------------------


class TestV8FieldPathBracketGrammar:
    """V8: bracket content and segment names are stored without validation."""

    @pytest.mark.parametrize(
        "path_str",
        [
            "items[2]",
            "items[-1]",
            "flags[true]",
            'labels["env"]',
            "items[id=42]",
            'items[id="a"]',
        ],
    )
    def test_documented_bracket_forms_parse_and_round_trip_control(self, path_str: str) -> None:
        """Control: every bracket form the grammar declares parses and renders back."""
        path = FieldPath.parse(path_str)

        assert str(path) == path_str
        assert FieldPath.parse(str(path)) == path

    @pytest.mark.parametrize("path_str", ["items[", "items[0", "items[0]x", "items."])
    def test_parser_already_rejects_other_malformed_paths_control(self, path_str: str) -> None:
        """Control: ``parse`` does raise ``ValueError`` for the malformations it checks.

        The pin below asks for the same error on bracket CONTENT, which is the
        one part of the grammar the parser does not read.
        """
        with pytest.raises(ValueError):
            FieldPath.parse(path_str)

    @pytest.mark.parametrize(
        "path_str",
        [
            pytest.param("items[]", id="empty"),
            pytest.param("items[+1]", id="plus-signed-int"),
            pytest.param("items[TRUE]", id="uppercase-bool"),
            pytest.param("items[id=]", id="key-without-value"),
            pytest.param("labels[env]", id="unquoted-string"),
            pytest.param("labels[[0]", id="stray-open-bracket"),
            pytest.param('a["x\\q"]', id="unknown-escape"),
            pytest.param('a["\x01"]', id="raw-control-character"),
            pytest.param('a["\u2028"]', id="raw-line-separator"),
            pytest.param('a[b"\xe9"]', id="non-ascii-in-bytes"),
            pytest.param('a[b"\\x4"]', id="truncated-hex-escape"),
            pytest.param('a["x"y"]', id="unescaped-inner-quote"),
        ],
    )
    def test_bracket_content_outside_the_grammar_must_be_rejected(self, path_str: str) -> None:
        """A bracket that is none of the declared key forms must raise ``ValueError``.

        User-visible consequence: ``DiffResult.filter(path="labels[env]")`` (and
        ``protokit diff --filter``) accepts a mistyped key and returns zero
        differences, because the stored bracket ``env`` never equals the
        ``"env"`` a real path carries. The caller reads an empty result as "no
        differences there" when the filter was malformed.
        """
        # 0.16.0: each of these parsed; the bracket is stored verbatim.
        with pytest.raises(ValueError):
            FieldPath.parse(path_str)

    def test_single_name_children_round_trip_control(self) -> None:
        """Control: ``child`` with one grammar name per call round-trips through ``parse``.

        A parenthesised extension name is ONE name despite its dots, so it
        round-trips too. The pin below is about a name that is not one name.
        """
        plain = FieldPath(segments=()).child("a").child("b")
        extension = FieldPath(segments=()).child("inner").child("(pkg.ext)", "0")

        assert (str(plain), len(plain.segments)) == ("a.b", 2)
        assert FieldPath.parse(str(plain)) == plain
        assert (str(extension), len(extension.segments)) == ("inner.(pkg.ext)[0]", 2)
        assert FieldPath.parse(str(extension)) == extension

    def test_child_with_a_dotted_name_must_reject_or_round_trip(self) -> None:
        """A path built with ``child`` must survive ``parse(str(path))`` unchanged.

        User-visible consequence: a path a hook or caller builds with
        ``child("a.b")`` prints exactly like the two-segment path ``a.b`` but
        does not equal it, and an exact-length selector that matches one does
        not match the other. Two paths that print the same compare differently.

        Either remedy flips this pin: rejecting the name at construction
        returns early, and a rendering that round-trips passes the assertion.
        """
        try:
            path = FieldPath(segments=()).child("a.b")
        except ValueError:
            # Construction now rejects a name that is not one grammar name.
            return

        # 0.16.0: one segment named "a.b"; the reparse yields two segments.
        assert FieldPath.parse(str(path)) == path


# ---------------------------------------------------------------------------
# V12 — a plain bare name reaches a different depth under different policies
# ---------------------------------------------------------------------------


def _depth_builder() -> ProtoBuilder:
    """``Outer { name, value, tags, Inner inner }`` and ``Inner { name, value, tags }``.

    Every plain field name exists at the top level AND one level down, so a
    bare selector's reach shows up as "top level only" versus "every depth".
    """
    fields: dict[str, tuple[int, int] | tuple[int, int, str]] = {
        "name": (T.TYPE_STRING, 1),
        "value": (T.TYPE_DOUBLE, 2),
        "tags": (T.TYPE_STRING, 3),
    }
    b = ProtoBuilder()
    b.message("test.Inner", fields, repeated_fields={"tags"})
    b.message(
        "test.Outer",
        {**fields, "inner": (T.TYPE_MESSAGE, 4, ".test.Inner")},
        repeated_fields={"tags"},
    )
    return b


def _names_differ_at_both_depths() -> tuple[Message, Message]:
    """Two ``Outer`` messages whose ``name`` AND ``inner.name`` both differ."""
    b = _depth_builder()
    inner = b.get_message_class("test.Inner")
    left = b.build("test.Outer", name="a", inner=inner(name="x"))
    right = b.build("test.Outer", name="b", inner=inner(name="y"))
    return left, right


def _values_differ_within_tolerance(*, nested: bool) -> tuple[Message, Message]:
    """Two ``Outer`` messages whose ``value`` is 1.0 vs 1.0000001 at one depth."""
    b = _depth_builder()
    inner = b.get_message_class("test.Inner")
    if nested:
        return (
            b.build("test.Outer", inner=inner(value=1.0)),
            b.build("test.Outer", inner=inner(value=1.0000001)),
        )
    return b.build("test.Outer", value=1.0), b.build("test.Outer", value=1.0000001)


def _tags_reordered(*, nested: bool) -> tuple[Message, Message]:
    """Two ``Outer`` messages holding the same ``tags`` in a different order at one depth."""
    b = _depth_builder()
    inner = b.get_message_class("test.Inner")
    if nested:
        return (
            b.build("test.Outer", inner=inner(tags=["a", "b"])),
            b.build("test.Outer", inner=inner(tags=["b", "a"])),
        )
    return b.build("test.Outer", tags=["a", "b"]), b.build("test.Outer", tags=["b", "a"])


def _exact_overlay_differ(selector: str) -> MessageDifferencer:
    """A differ comparing floats approximately, with an EXACT overlay on ``selector``."""
    d = MessageDifferencer()
    d.set_float_comparison(FloatComparison.APPROXIMATE, fraction=1e-3)
    d.set_float_comparison(FloatComparison.EXACT, selector=selector)
    return d


class TestV12BareNameReachDiffersByPolicy:
    """V12: one bare name, any depth under two policies and top level under three."""

    def test_string_bare_name_ignores_the_field_at_every_depth_control(self) -> None:
        """Control: ``ignore_fields("name")`` is documented to ignore ``name`` everywhere.

        The unconfigured comparison reports both ``name`` fields, so the empty
        result is the selector's doing. This is the reference answer the object
        spelling below must give.
        """
        left, right = _names_differ_at_both_depths()

        assert _observed(MessageDifferencer().compare(left, right)) == [
            ("inner.name", "MODIFIED"),
            ("name", "MODIFIED"),
        ]

        d = MessageDifferencer()
        d.ignore_fields("name")
        assert _observed(d.compare(left, right)) == []

    @pytest.mark.parametrize("as_object", [False, True], ids=["string", "field-selector"])
    def test_dotted_selector_means_the_same_in_both_spellings_control(
        self, as_object: bool
    ) -> None:
        """Control: for a DOTTED selector the string and object spellings already agree."""
        left, right = _names_differ_at_both_depths()

        d = MessageDifferencer()
        d.ignore_fields(FieldSelector.of("inner.name") if as_object else "inner.name")

        assert _observed(d.compare(left, right)) == [("name", "MODIFIED")]

    def test_field_selector_spelling_of_a_bare_name_must_ignore_the_same_fields(self) -> None:
        """``ignore_fields(FieldSelector.of(s))`` must equal ``ignore_fields(s)``.

        User-visible consequence: wrapping a selector in ``FieldSelector.of`` —
        documented as the object form of the same string — silently narrows it
        to the top level. A nested timestamp the caller meant to ignore comes
        back as a difference, or, read the other way, the string form hides
        nested differences the object form reports.
        """
        left, right = _names_differ_at_both_depths()

        d = MessageDifferencer()
        d.ignore_fields(FieldSelector.of("name"))

        # 0.16.0: [('inner.name', 'MODIFIED')].
        assert _observed(d.compare(left, right)) == []

    @pytest.mark.parametrize(
        ("selector", "nested", "expected_path"),
        [
            pytest.param("value", False, "value", id="bare-name-at-top-level"),
            pytest.param("inner.value", True, "inner.value", id="dotted-path-one-level-down"),
        ],
    )
    def test_exact_overlay_reports_the_difference_where_it_matches_control(
        self, selector: str, nested: bool, expected_path: str
    ) -> None:
        """Control: an EXACT overlay over an APPROXIMATE default reports 1.0 vs 1.0000001.

        It does so for the bare name at the top level and for the dotted path
        one level down, so the construction is sound at both depths.
        """
        left, right = _values_differ_within_tolerance(nested=nested)

        result = _exact_overlay_differ(selector).compare(left, right)

        assert _observed(result) == [(expected_path, "MODIFIED")]

    def test_bare_name_exact_overlay_must_apply_one_level_down(self) -> None:
        """A bare-name float overlay must reach the field wherever it sits.

        User-visible consequence: a silent false EQUAL. The caller relaxed
        floats globally and then demanded bit-exact comparison for ``value``;
        a nested ``value`` that differs is reported as identical and nothing
        is printed.
        """
        left, right = _values_differ_within_tolerance(nested=True)

        result = _exact_overlay_differ("value").compare(left, right)

        # 0.16.0: [] — has_changes() is False.
        assert _observed(result) == [("inner.value", "MODIFIED")]

    @pytest.mark.parametrize(
        ("selector", "nested"),
        [
            pytest.param("tags", False, id="bare-name-at-top-level"),
            pytest.param("inner.tags", True, id="dotted-path-one-level-down"),
        ],
    )
    def test_treat_as_set_pairs_reordered_tags_where_it_matches_control(
        self, selector: str, nested: bool
    ) -> None:
        """Control: ``treat_as_set`` makes a reordered list compare equal at both depths."""
        left, right = _tags_reordered(nested=nested)

        d = MessageDifferencer()
        d.treat_as_set(selector)

        assert _observed(d.compare(left, right)) == []

    def test_bare_name_treat_as_set_must_apply_one_level_down(self) -> None:
        """A bare-name set selector must reach the field wherever it sits.

        User-visible consequence: ``treat_as_map("items", ...)`` and
        ``treat_as_set("tags")`` read as the same kind of instruction, but only
        the first reaches a nested field. A nested list the caller declared
        order-independent is still compared by position, so the same set of
        values is reported as differences.
        """
        left, right = _tags_reordered(nested=True)

        d = MessageDifferencer()
        d.treat_as_set("tags")

        # 0.16.0: [('inner.tags[0]', 'MODIFIED'), ('inner.tags[1]', 'MODIFIED')].
        assert _observed(d.compare(left, right)) == []

    @pytest.mark.parametrize("map_first", [True, False], ids=["map-then-set", "set-then-map"])
    def test_same_bare_name_as_map_and_set_is_rejected_control(self, map_first: bool) -> None:
        """Control: the keyed/keyless conflict guard fires when both selectors are ``items``."""
        d = MessageDifferencer()

        with pytest.raises(ValueError, match="treat_as_"):
            if map_first:
                d.treat_as_map("items", key="id")
                d.treat_as_set("items")
            else:
                d.treat_as_set("items")
                d.treat_as_map("items", key="id")

    @pytest.mark.parametrize("map_first", [True, False], ids=["map-then-set", "set-then-map"])
    def test_bare_name_map_must_conflict_with_a_set_on_the_same_nested_field(
        self, map_first: bool
    ) -> None:
        """A field cannot be both keyed and keyless, however the two selectors are spelled.

        User-visible consequence: ``treat_as_map("items", key="id")`` keys
        ``outer.items`` because a bare name applies everywhere, and
        ``treat_as_set("outer.items")`` names that same field. ``treat_as_set``
        documents ``ValueError`` for a selector that overlaps a ``treat_as_map``
        selector; instead both registrations succeed, the map wins at compare
        time and the set request has no effect, with no error and no diagnostic.
        """
        d = MessageDifferencer()

        # 0.16.0: both orders were accepted.
        with pytest.raises(ValueError, match="treat_as_"):
            if map_first:
                d.treat_as_map("items", key="id")
                d.treat_as_set("outer.items")
            else:
                d.treat_as_set("outer.items")
                d.treat_as_map("items", key="id")


# ---------------------------------------------------------------------------
# V13 — bracket selectors are accepted and widen to every element
# ---------------------------------------------------------------------------


def _ratios_pair() -> tuple[Message, Message]:
    """Two ``M { repeated double ratios }``: element 0 equal, element 1 is 2.0 vs 2.0005."""
    b = ProtoBuilder()
    b.message("test.M", {"ratios": (T.TYPE_DOUBLE, 1)}, repeated_fields={"ratios"})
    return b.build("test.M", ratios=[1.0, 2.0]), b.build("test.M", ratios=[1.0, 2.0005])


def _item_names_pair() -> tuple[Message, Message]:
    """Two ``C { repeated Item items }``: element 0 equal, element 1's ``name`` differs."""
    b = ProtoBuilder()
    b.message("test.Item", {"name": (T.TYPE_STRING, 1)})
    b.message_with_repeated(
        "test.C",
        {"items": (T.TYPE_MESSAGE, 1, ".test.Item")},
        repeated_fields={"items"},
    )
    item = b.get_message_class("test.Item")
    left = b.build("test.C", items=[item(name="a"), item(name="b")])
    right = b.build("test.C", items=[item(name="a"), item(name="z")])
    return left, right


class TestV13BracketSelectorsAcceptedAndWidened:
    """V13: only the string form of ``ignore_fields`` refuses a bracket selector."""

    @pytest.mark.parametrize("selector", ["ratios[0]", "items[0].name"])
    def test_string_form_ignore_rejects_a_bracket_selector_control(self, selector: str) -> None:
        """Control: ``ignore_fields`` given a bracket STRING raises, and says why.

        This is the rejection the pins below ask every other entry point for.
        """
        d = MessageDifferencer()

        with pytest.raises(ValueError, match="Bracket syntax is not supported"):
            d.ignore_fields(selector)

    def test_bracket_free_overlay_relaxes_every_element_control(self) -> None:
        """Control: the bracket-free ``ratios`` overlay is the way to relax all elements.

        Unconfigured, element 1 is reported; with the overlay on ``ratios`` it
        is within tolerance. So the construction is sound, and "every element"
        is what the bracket-FREE spelling means.
        """
        left, right = _ratios_pair()

        assert _observed(MessageDifferencer().compare(left, right)) == [("ratios[1]", "MODIFIED")]

        d = MessageDifferencer()
        d.set_float_comparison(FloatComparison.APPROXIMATE, fraction=1e-3, selector="ratios")
        assert _observed(d.compare(left, right)) == []

    def test_bracket_free_object_ignore_suppresses_every_element_control(self) -> None:
        """Control: ``FieldSelector.of("items.name")`` ignores ``name`` in all elements."""
        left, right = _item_names_pair()

        assert _observed(MessageDifferencer().compare(left, right)) == [
            ("items[1].name", "MODIFIED"),
        ]

        d = MessageDifferencer()
        d.ignore_fields(FieldSelector.of("items.name"))
        assert _observed(d.compare(left, right)) == []

    @pytest.mark.parametrize(
        "build",
        [
            pytest.param(FieldSelector.of, id="of"),
            pytest.param(FieldSelector.from_path, id="from_path"),
            pytest.param(lambda s: FieldSelector(path=FieldPath.parse(s)), id="path-keyword"),
        ],
    )
    def test_field_selector_construction_must_reject_a_bracket_selector(
        self, build: Callable[[str], FieldSelector]
    ) -> None:
        """Every way of building a path-form selector must refuse brackets.

        User-visible consequence: the object form is the escape hatch around
        the validation the string form enforces. ``FieldSelector.of`` documents
        ``ValueError`` for a spec that "contains bracket syntax" and
        ``from_path`` says "Brackets are not permitted in selector strings";
        neither refuses one.
        """
        # 0.16.0: all three return a selector whose path is items[0].name.
        with pytest.raises(ValueError):
            build("items[0].name")

    @pytest.mark.parametrize(
        "register",
        [
            pytest.param(lambda d: d.treat_as_set("ratios[0]"), id="treat_as_set"),
            pytest.param(
                lambda d: d.set_float_comparison(
                    FloatComparison.APPROXIMATE, fraction=1e-3, selector="ratios[0]",
                ),
                id="float-overlay",
            ),
            pytest.param(
                lambda d: d.ignore_fields(FieldSelector.of("ratios[0]")),
                id="ignore-field-selector",
            ),
        ],
    )
    def test_policy_registration_must_reject_a_bracket_selector(
        self, register: Callable[[MessageDifferencer], None]
    ) -> None:
        """A bracket selector must be refused by every policy, not by one spelling of one.

        User-visible consequence: the same selector text is a usage error under
        ``ignore_fields("ratios[0]")`` and silently accepted under three other
        registrations, where it then means something else (pinned below).
        """
        d = MessageDifferencer()

        # 0.16.0: all three registrations succeed.
        with pytest.raises(ValueError):
            register(d)

    def test_bracket_overlay_must_not_relax_the_other_elements(self) -> None:
        """A tolerance asked for element 0 must not hide a difference in element 1.

        User-visible consequence: a silent false EQUAL. The caller scoped a
        relaxed tolerance to one element and every element got it.

        Either remedy flips this pin: rejecting the selector at registration
        returns early, and honouring the index reports ``ratios[1]``.
        """
        left, right = _ratios_pair()
        d = MessageDifferencer()
        try:
            d.set_float_comparison(
                FloatComparison.APPROXIMATE, fraction=1e-3, selector="ratios[0]",
            )
        except ValueError:
            # Registration now rejects the bracket selector: nothing can widen.
            return

        # 0.16.0: [] — has_changes() is False.
        assert _observed(d.compare(left, right)) == [("ratios[1]", "MODIFIED")]

    def test_bracket_object_ignore_must_not_suppress_the_other_elements(self) -> None:
        """Ignoring ``items[0].name`` must not ignore ``items[1].name``.

        User-visible consequence: over-suppression of real differences. The
        caller asked to ignore one element's field and lost every element's.

        Either remedy flips this pin, as above.
        """
        left, right = _item_names_pair()
        d = MessageDifferencer()
        try:
            d.ignore_fields(FieldSelector.of("items[0].name"))
        except ValueError:
            # Construction now rejects the bracket selector: nothing can widen.
            return

        # 0.16.0: [] — has_changes() is False.
        assert _observed(d.compare(left, right)) == [("items[1].name", "MODIFIED")]


# ---------------------------------------------------------------------------
# V13 (treat_as_map) — a bracket selector is accepted and then never applies
#
# Reproduced during the 0.16.0 re-audit and pinned on 2026-10-11. It has no
# finding ID of its own and is owned by U9 (0.17.0) with V13.
# ``treat_as_map`` checks its selector for conflicts and never for brackets,
# so ``treat_as_map("items[0]", key="id")`` registers. Where the other
# policies widen an accepted bracket selector to every element, a one-segment
# map selector matches nothing: it is stored under its literal text and looked
# up by bare field name, and ``"items[0]"`` is never ``"items"``. The field
# keeps positional pairing and the caller is not told.
# ---------------------------------------------------------------------------


def _reordered_items_pair() -> tuple[Message, Message]:
    """Two ``C { repeated Item items }`` holding the same two items in opposite order."""
    b = ProtoBuilder()
    b.message("test.Item", {"id": (T.TYPE_INT32, 1), "name": (T.TYPE_STRING, 2)})
    b.message_with_repeated(
        "test.C",
        {"items": (T.TYPE_MESSAGE, 1, ".test.Item")},
        repeated_fields={"items"},
    )
    item = b.get_message_class("test.Item")
    left = b.build("test.C", items=[item(id=1, name="a"), item(id=2, name="b")])
    right = b.build("test.C", items=[item(id=2, name="b"), item(id=1, name="a")])
    return left, right


class TestV13TreatAsMapAcceptsABracketSelector:
    """V13 (treat_as_map): the one policy whose bracket selector silently does nothing."""

    def test_bracket_free_map_selector_pairs_a_reorder_by_key_control(self) -> None:
        """Control: ``treat_as_map("items", key="id")`` is what makes a reorder equal.

        Unconfigured, the reordered pair differs at every position. Keyed on
        ``id`` it has no differences. So the construction is sound and the
        four positional differences below mean the map policy did not apply.
        """
        left, right = _reordered_items_pair()

        assert _observed(MessageDifferencer().compare(left, right)) == [
            ("items[0].id", "MODIFIED"),
            ("items[0].name", "MODIFIED"),
            ("items[1].id", "MODIFIED"),
            ("items[1].name", "MODIFIED"),
        ]

        d = MessageDifferencer()
        d.treat_as_map("items", key="id")
        assert _observed(d.compare(left, right)) == []

    @pytest.mark.parametrize("selector", ["items[0]", "items[1]", "outer.items[0]"])
    def test_treat_as_map_must_reject_a_bracket_selector(self, selector: str) -> None:
        """``treat_as_map`` must refuse a bracket selector as ``ignore_fields`` does.

        User-visible consequence: a selector that cannot mean anything for a
        keyed field (a map has no element 0) is accepted without a word.
        """
        d = MessageDifferencer()

        # 0.16.0: the registration succeeded.
        with pytest.raises(ValueError):
            d.treat_as_map(selector, key="id")

    def test_bracket_map_selector_must_not_fall_back_to_positional_pairing(self) -> None:
        """A caller who asked for keyed matching must not get positional matching unannounced.

        User-visible consequence: false differences. The caller configured the
        field as a map, the two messages hold the same items, and the result
        says every leaf changed.

        Rejecting the selector at registration flips this pin through the
        early return. Applying the map policy to ``items`` would flip it too;
        the pin above stays red in that case, because the selector was still
        accepted.
        """
        left, right = _reordered_items_pair()
        d = MessageDifferencer()
        try:
            d.treat_as_map("items[0]", key="id")
        except ValueError:
            # Registration now rejects the bracket selector: nothing is silently dropped.
            return

        # 0.16.0: the four positional MODIFIED leaves of the control above.
        assert _observed(d.compare(left, right)) == []


# ---------------------------------------------------------------------------
# C19-C1 (= R12-C1), with C19-C1b — a map key lands raw in the diff path
#
# Reproduced again by the second 0.16.0 re-audit and pinned on 2026-10-17,
# owned by U9 (0.17.0). ``format_key`` puts a string key in the path bracket
# with only ``\`` and ``"`` escaped. A newline, a carriage return or an ESC in
# the key therefore reaches the rendered path unchanged, and the human and
# JUnit reports, which print one line per difference, print this one over
# several. The JSON report is unaffected (its encoder escapes the string), and
# the same text as a string VALUE is escaped by ``repr``. C19-C1b is the same
# key under a message extension and under a proto2 group, which 0.16.0 began
# to walk. How the key should be escaped is not settled, so the pins assert
# only what any escape gives: the difference renders with as many lines, and
# as many ESC bytes, as the same difference under a plain key.
# ---------------------------------------------------------------------------

_MAP_ENTRY = """nested_type { name: "LabelsEntry"
    field { name: "key" number: 1 type: TYPE_STRING label: LABEL_OPTIONAL }
    field { name: "value" number: 2 type: TYPE_STRING label: LABEL_OPTIONAL }
    options { map_entry: true } }"""

#: ``M`` has a ``map<string, string> labels``, a group ``grp`` holding its own
#: ``labels`` map, and a message extension ``(test.ext)`` whose ``Ext`` has one.
_KEY_CARRIERS_FILE = f"""
name: "c19.proto" package: "test" syntax: "proto2"
message_type {{ name: "Ext"
  field {{ name: "labels" number: 1 type: TYPE_MESSAGE
          type_name: ".test.Ext.LabelsEntry" label: LABEL_REPEATED }}
  field {{ name: "x" number: 2 type: TYPE_INT32 label: LABEL_OPTIONAL }}
  {_MAP_ENTRY} }}
message_type {{ name: "M"
  field {{ name: "labels" number: 1 type: TYPE_MESSAGE
          type_name: ".test.M.LabelsEntry" label: LABEL_REPEATED }}
  field {{ name: "grp" number: 2 type: TYPE_GROUP type_name: ".test.M.Grp"
          label: LABEL_OPTIONAL }}
  nested_type {{ name: "Grp"
    field {{ name: "labels" number: 1 type: TYPE_MESSAGE
            type_name: ".test.M.Grp.LabelsEntry" label: LABEL_REPEATED }}
    field {{ name: "a" number: 2 type: TYPE_INT32 label: LABEL_OPTIONAL }}
    {_MAP_ENTRY} }}
  {_MAP_ENTRY}
  extension_range {{ start: 100 end: 200 }} }}
extension {{ name: "ext" extendee: ".test.M" number: 100 type: TYPE_MESSAGE
             type_name: ".test.Ext" label: LABEL_OPTIONAL }}
"""

#: A key holding a newline, a carriage return and an ESC sequence (erase line).
_CONTROL_CHAR_KEY = "x\nMessages are equal.\ry\x1b[2K"

_LOCATIONS = ["declared-map", "message-extension", "group"]

#: The path of a difference at each location, for the plain key ``k``.
_PLAIN_KEY_PATHS = {
    "declared-map": 'labels["k"]',
    "message-extension": '(test.ext).labels["k"]',
    "group": 'grp.labels["k"]',
}


def _key_carrier_pair(
    location: str, *, key: str, left_value: str | None, right_value: str
) -> tuple[Message, Message]:
    """Two ``M`` messages whose map at ``location`` differs in the entry ``key``.

    ``left_value=None`` leaves the entry out on the left, so the difference is
    an added key; a string makes it a changed value. Both sides set the
    carrier's other field (``(test.ext).x``, ``grp.a``), so the carrier itself
    is present on both and the map entry is the only difference.
    """
    pool = descriptor_pool.DescriptorPool()
    pool.Add(text_format.Parse(_KEY_CARRIERS_FILE, descriptor_pb2.FileDescriptorProto()))
    cls = message_factory.GetMessageClassesForFiles(["c19.proto"], pool)["test.M"]
    extension = pool.FindExtensionByName("test.ext")

    left, right = cls(), cls()
    for message, value in ((left, left_value), (right, right_value)):
        if location == "declared-map":
            labels = message.labels
        elif location == "message-extension":
            message.Extensions[extension].x = 1
            labels = message.Extensions[extension].labels
        else:
            message.grp.a = 1
            labels = message.grp.labels
        if value is not None:
            labels[key] = value
    return left, right


def _added_key(location: str, key: str) -> DiffResult:
    """The comparison of an empty map against one holding ``{key: "v"}`` at ``location``."""
    left, right = _key_carrier_pair(location, key=key, left_value=None, right_value="v")
    return MessageDifferencer().compare(left, right)


def _render(output_format: str, result: DiffResult) -> str:
    """``result`` rendered by the built-in diff formatter ``output_format``."""
    formatter = get_formatter(output_format, FormatterKind.DIFF)
    return formatter(result, FormatterContext(subcommand="diff"))


def _rendered_shape(output_format: str, result: DiffResult) -> tuple[int, int]:
    """``(line count, ESC count)`` of the text that carries the differences.

    Human: the whole report, lines counted with styling removed and ESC
    counted with it kept, so the report's own styling is the same on both
    sides of a comparison and only the key's ESC adds to the count. JUnit:
    the failure body as an XML parser hands it back. JSON: the document.
    ``splitlines`` counts a carriage return as a line break, as a terminal and
    an XML parser both treat it.
    """
    rendered = _render(output_format, result)
    if output_format == "human":
        return len(click.unstyle(rendered).splitlines()), rendered.count("\x1b")
    if output_format == "junit":
        failure = ET.fromstring(rendered).find("./testcase/failure")
        assert failure is not None, rendered
        body = failure.text or ""
        return len(body.splitlines()), body.count("\x1b")
    return len(rendered.splitlines()), rendered.count("\x1b")


class TestC19C1MapKeyLandsRawInTheDiffPath:
    """C19-C1: a string map key's control characters reach the rendered path."""

    @pytest.mark.parametrize("location", _LOCATIONS)
    def test_a_plain_key_is_one_difference_at_every_location_control(
        self, location: str
    ) -> None:
        """Control: each location carries the key into the diff path.

        Without this, the extension and group cases could pass the pin by
        never reaching the key (0.15.1 compared neither carrier this way).
        The same construction with the control-character key is also one
        difference, so the pin below compares like with like.
        """
        result = _added_key(location, "k")

        assert _observed(result) == [(_PLAIN_KEY_PATHS[location], "ADDED")]
        assert len(_added_key(location, _CONTROL_CHAR_KEY)) == 1

    @pytest.mark.parametrize("location", _LOCATIONS)
    def test_json_report_keeps_the_difference_on_one_line_control(self, location: str) -> None:
        """Control: the JSON report already escapes the key.

        The document parses, reports the one difference, and has exactly as
        many lines and ESC bytes as the same report for the plain key. This
        stays true whatever escape the fix picks for the path text.
        """
        result = _added_key(location, _CONTROL_CHAR_KEY)
        document = json.loads(_render("json", result))

        assert (document["equal"], len(document["differences"])) == (False, 1)
        assert _rendered_shape("json", result) == _rendered_shape(
            "json", _added_key(location, "k")
        )

    @pytest.mark.parametrize("output_format", ["human", "junit"])
    @pytest.mark.parametrize("location", _LOCATIONS)
    def test_the_same_text_as_a_value_is_escaped_control(
        self, location: str, output_format: str
    ) -> None:
        """Control: the same characters in a map VALUE stay on one line.

        ``labels["k"]`` changes from ``"a"`` to the control-character text and
        renders exactly like a change to ``"b"``: the value is escaped. Only
        the key is not.
        """
        noisy = _key_carrier_pair(
            location, key="k", left_value="a", right_value=_CONTROL_CHAR_KEY
        )
        plain = _key_carrier_pair(location, key="k", left_value="a", right_value="b")

        noisy_result = MessageDifferencer().compare(*noisy)
        plain_result = MessageDifferencer().compare(*plain)

        assert _observed(noisy_result) == [(_PLAIN_KEY_PATHS[location], "MODIFIED")]
        assert _rendered_shape(output_format, noisy_result) == _rendered_shape(
            output_format, plain_result
        )

    @pytest.mark.parametrize("output_format", ["human", "junit"])
    @pytest.mark.parametrize("location", _LOCATIONS)
    def test_a_control_character_key_must_render_as_one_difference_on_one_line(
        self, location: str, output_format: str
    ) -> None:
        """A key's control characters must not change how the report is laid out.

        User-visible consequence: one added key prints as three lines, the
        middle one starting at column 0 with whatever text the key carries, so
        data can write ``Messages are equal.`` as a line of its own into a
        report that found a difference; in the human report an ESC sequence
        in the key reaches the terminal and can rewrite what is already on it.
        A CI log or a JUnit viewer shows lines no difference produced.

        The escape form is not settled, so the pin compares against the same
        difference under the plain key ``k``: equal line counts and equal ESC
        counts hold for any escape the fix picks.
        """
        result = _added_key(location, _CONTROL_CHAR_KEY)

        # 0.16.0: two more lines than the plain key (the newline and the
        # carriage return), and in the human report one more ESC.
        assert _rendered_shape(output_format, result) == _rendered_shape(
            output_format, _added_key(location, "k")
        )
