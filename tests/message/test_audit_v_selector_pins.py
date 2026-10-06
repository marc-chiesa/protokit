"""Regression pins for DEFERRED message-selector audit findings (family V).

Every ``xfail`` in this module pins a LIVE defect a later release owns. The
findings are defined in ``docs/plans/AUDIT-whole-codebase-2026-08-30.md`` and
were reproduced again, unpinned, by the cycle-1 re-audit
(``docs/plans/AUDIT-cycle-1-2026-09-27.md``, rows R05-C2, R10-C1 and R10-C2).
All three are owned by unit U9 ("Selector unification") of the stability
release plan, which lands in 0.17.0.

The pins are strict. Each is ``@pytest.mark.xfail(strict=True, raises=...)``
with a ``reason`` that leads with the finding ID and names the owning unit and
release, so the suite stays green while the defect exists and each pin flips to
a hard failure (XPASS) the day the mechanism is fixed. ``raises=`` is the
exception the pin was observed to fail with under ``--runxfail --tb=line`` on
both protobuf backends, so a failure for any other reason is a plain FAILED.

Each pin asserts the correct outcome, not "something changed". Green control
tests sit beside the pins and share their construction: they show the harness
reaches the comparison and that the wrong outcome is specific to the pinned
mechanism. The controls assert behaviour that is correct today and stays
correct after the fix.

Pinned here:

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
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from google.protobuf import descriptor_pb2
from google.protobuf.message import Message

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
        ],
    )
    @pytest.mark.xfail(
        strict=True,
        raises=pytest.fail.Exception,
        reason="V8: owned by U9 (0.17.0). FieldPath.parse stores whatever sits between "
               "'[' and ']' as PathSegment.bracket without checking it against the bracket "
               "grammar model.py declares (signed int, true/false, quoted string, "
               "name=value), so a malformed key parses instead of raising the ValueError "
               "parse() documents for a malformed path",
    )
    def test_bracket_content_outside_the_grammar_must_be_rejected(self, path_str: str) -> None:
        """A bracket that is none of the declared key forms must raise ``ValueError``.

        User-visible consequence: ``DiffResult.filter(path="labels[env]")`` (and
        ``protokit diff --filter``) accepts a mistyped key and returns zero
        differences, because the stored bracket ``env`` never equals the
        ``"env"`` a real path carries. The caller reads an empty result as "no
        differences there" when the filter was malformed.
        """
        # Today each of these parses; the bracket is stored verbatim.
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

    @pytest.mark.xfail(
        strict=True,
        raises=AssertionError,
        reason="V8: owned by U9 (0.17.0). FieldPath.child (through PathSegment) accepts a "
               "name that is not one grammar name, so child('a.b') builds ONE segment that "
               "renders as 'a.b' and parses back as TWO — parse(str(path)) != path, and "
               "selector matching counts segments",
    )
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

        # Today: one segment named "a.b"; the reparse yields two segments.
        assert FieldPath.parse(str(path)) == path


# ---------------------------------------------------------------------------
# V12 — a plain bare name reaches a different depth under different policies
# ---------------------------------------------------------------------------


def _depth_pool() -> ProtoBuilder:
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
    b = _depth_pool()
    inner = b.get_message_class("test.Inner")
    left = b.build("test.Outer", name="a", inner=inner(name="x"))
    right = b.build("test.Outer", name="b", inner=inner(name="y"))
    return left, right


def _values_differ_within_tolerance(*, nested: bool) -> tuple[Message, Message]:
    """Two ``Outer`` messages whose ``value`` is 1.0 vs 1.0000001 at one depth."""
    b = _depth_pool()
    inner = b.get_message_class("test.Inner")
    if nested:
        return (
            b.build("test.Outer", inner=inner(value=1.0)),
            b.build("test.Outer", inner=inner(value=1.0000001)),
        )
    return b.build("test.Outer", value=1.0), b.build("test.Outer", value=1.0000001)


def _tags_reordered(*, nested: bool) -> tuple[Message, Message]:
    """Two ``Outer`` messages holding the same ``tags`` in a different order at one depth."""
    b = _depth_pool()
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

    @pytest.mark.xfail(
        strict=True,
        raises=AssertionError,
        reason="V12: owned by U9 (0.17.0). ignore_fields routes a bare-name STRING to "
               "_ignore_names (matched at any depth) and a FieldSelector to "
               "_ignore_selectors (exact segment count, so top level only): "
               "FieldSelector.of('name') leaves inner.name reported where the string "
               "'name' ignores it",
    )
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

        # Today: [('inner.name', 'MODIFIED')].
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

    @pytest.mark.xfail(
        strict=True,
        raises=AssertionError,
        reason="V12: owned by U9 (0.17.0). A set_float_comparison overlay selector is a "
               "FieldSelector, so the bare name 'value' matches only a top-level field: "
               "inner.value falls back to the global APPROXIMATE config and 1.0 vs "
               "1.0000001 compares EQUAL although the caller asked for EXACT on 'value'",
    )
    def test_bare_name_exact_overlay_must_apply_one_level_down(self) -> None:
        """A bare-name float overlay must reach the field wherever it sits.

        User-visible consequence: a silent false EQUAL. The caller relaxed
        floats globally and then demanded bit-exact comparison for ``value``;
        a nested ``value`` that differs is reported as identical and nothing
        is printed.
        """
        left, right = _values_differ_within_tolerance(nested=True)

        result = _exact_overlay_differ("value").compare(left, right)

        # Today: [] — has_changes() is False.
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

    @pytest.mark.xfail(
        strict=True,
        raises=AssertionError,
        reason="V12: owned by U9 (0.17.0). treat_as_set stores a FieldSelector, so the bare "
               "name 'tags' selects only a top-level field, while the same bare name given "
               "to treat_as_map applies at any depth: a reordered inner.tags is compared by "
               "index and reported as two MODIFIED elements",
    )
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

        # Today: [('inner.tags[0]', 'MODIFIED'), ('inner.tags[1]', 'MODIFIED')].
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
    @pytest.mark.xfail(
        strict=True,
        raises=pytest.fail.Exception,
        reason="V12: owned by U9 (0.17.0). The keyed/keyless conflict guard compares the "
               "two selectors by exact segment count, so it does not see that the bare "
               "name 'items' — which treat_as_map applies at any depth — also selects "
               "'outer.items': registering both is accepted and the set selector is then "
               "silently ignored",
    )
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

        # Today both orders are accepted.
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
    @pytest.mark.xfail(
        strict=True,
        raises=pytest.fail.Exception,
        reason="V13: owned by U9 (0.17.0). FieldSelector construction never checks its "
               "path for brackets (from_path is FieldPath.parse and nothing else), so "
               "'items[0].name' is accepted although of() documents ValueError for a "
               "string that contains bracket syntax",
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
        # Today all three return a selector whose path is items[0].name.
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
    @pytest.mark.xfail(
        strict=True,
        raises=pytest.fail.Exception,
        reason="V13: owned by U9 (0.17.0). treat_as_set, set_float_comparison(selector=) "
               "and the FieldSelector form of ignore_fields normalise through "
               "FieldSelector.of, which accepts brackets, so 'ratios[0]' registers where "
               "the string form of ignore_fields raises ValueError for the same text",
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

        # Today all three registrations succeed.
        with pytest.raises(ValueError):
            register(d)

    @pytest.mark.xfail(
        strict=True,
        raises=AssertionError,
        reason="V13: owned by U9 (0.17.0). Path-form matching ignores brackets, so an "
               "accepted overlay selector 'ratios[0]' selects every element: ratios[1] "
               "2.0 vs 2.0005 is compared with the relaxed tolerance and reported EQUAL",
    )
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

        # Today: [] — has_changes() is False.
        assert _observed(d.compare(left, right)) == [("ratios[1]", "MODIFIED")]

    @pytest.mark.xfail(
        strict=True,
        raises=AssertionError,
        reason="V13: owned by U9 (0.17.0). The same bracket-blind matching applied to an "
               "accepted ignore selector: FieldSelector.of('items[0].name') suppresses "
               "items[N].name for every N, so a difference in items[1].name disappears",
    )
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

        # Today: [] — has_changes() is False.
        assert _observed(d.compare(left, right)) == [("items[1].name", "MODIFIED")]
