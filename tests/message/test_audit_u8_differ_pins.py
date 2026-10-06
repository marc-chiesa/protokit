"""Regression pins for CONFIRMED message-differ audit findings (family U8).

Every ``xfail`` in this module pins a LIVE defect triaged in
``docs/plans/AUDIT-triage-2026-08-30.md``. Each pin is
``@pytest.mark.xfail(strict=True)`` with a ``reason`` that begins with the
finding ID, so the suite stays green while the defect exists and flips to a
hard failure the day the mechanism is fixed — a fix cannot land silently, and
the pin cannot rot into a permanently-red test.

Each pin asserts the *specific* correct outcome (the exact diff list, the exact
exception, the exact path form), not a vague "something differs", so making it
pass requires fixing the named mechanism. Green control tests sit beside the
pins: they establish that the construction is on a supported path and that the
wrong outcome is specific to the mechanism, so a pin that flips is evidence of
a fix rather than of drift.

Pinned here:

* **U8-2** — ``_compare_treat_as_set`` pairs elements with
  ``greedy_multiset_pairing``, whose documented load-bearing precondition
  (``_setmatch.py`` module docstring) is that the injected equality is *a true
  equivalence relation*, "so the greedy partition is order-independent". The
  equality it injects for cross-pool enums is "same name OR same number"
  (``compare_enum_cross_pool``), which is not transitive, so first-fit greedy
  pairing misses matchings that exist and the result depends on element order.
  KTD-8 in ``docs/plans/2026-06-07-001-feat-message-differ-expressive-matchers-plan.md``
  makes order-independence the unit's stated correctness pin and rules the
  opposite "explicitly out for v1" — while requiring, three sentences later,
  the cross-pool enum equality that breaks it.
* **U8-3** — ``_compare_map``'s key-type gate accepts any two integer key types
  as compatible, then the per-key membership test (``key not in right_map``)
  raises ``ValueError`` for a key not representable in the other side's key
  type. ``compare()`` documents only ``DuplicateKeyError`` / ``MissingKeyError``.
* **U8-4** — ``_emit_one_sided``'s repeated branch never calls
  ``_extract_keys``, so a ``treat_as_map`` field present on only one schema is
  emitted with index paths and without the documented ``DuplicateKeyError``.
  Its sibling one-sided route ``_emit_all_fields`` *does* key the same list, and
  says so in a comment: the errors "must not depend on whether the other side
  happened to carry this subtree".
* **U8-5** — ``ignore_fields``' ``treat_as_map`` key-conflict check only
  recognises the exact ``f"{map_sel}.{key_name}"`` spelling, so a more deeply
  qualified path naming the same key field is accepted and then erases the key.

Three V-series findings a later release owns are pinned at the end of this
module, in the same shape: **V28** (``treat_as_set`` drops ``ignore_fields``),
**V18** (a difference only in unknown fields is a silent EQUAL) and **V5** (a
proto2 ``[default = nan]`` never collapses as a default). They are defined in
``docs/plans/AUDIT-whole-codebase-2026-08-30.md``; the comment block above
that section gives each one's mechanism and owner.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
from click.testing import CliRunner
from google.protobuf import descriptor_pb2, descriptor_pool, message_factory
from google.protobuf.message import Message

from protokit.message import (
    ChangeType,
    DiffResult,
    DuplicateKeyError,
    MessageDifferencer,
    MessageFieldComparison,
)
from protokit.message.cli import main as diff_main
from tests.proto_builder import ProtoBuilder

T = descriptor_pb2.FieldDescriptorProto


# ---------------------------------------------------------------------------
# U8-2 — treat_as_set over the non-transitive cross-pool enum relation
# ---------------------------------------------------------------------------

# Two pools whose enum names and numbers are cross-wired: the name ``P`` moves
# from number 1 to number 5, and number 1 is reused by a new value ``Z``. Under
# ``compare_enum_cross_pool`` ("same name OR same number") this makes
# ``P(1) ~ P(5)`` (name), ``P(1) ~ Z(1)`` (number) and ``Q(5) ~ P(5)`` (number)
# while ``Q(5) !~ Z(1)`` — a relation that is NOT transitive.
_LEFT_ENUM = {"ZERO": 0, "P": 1, "Q": 5}
_RIGHT_ENUM = {"ZERO": 0, "Z": 1, "P": 5}


def _enum_tags_builder(values: dict[str, int]) -> ProtoBuilder:
    """Isolated-pool builder: ``Msg { repeated E tags = 1; }`` with ``E = values``."""
    b = ProtoBuilder()
    b.message(
        "test.Msg",
        {"tags": (T.TYPE_ENUM, 1, ".test.Msg.E")},
        enums={"E": values},
        repeated_fields={"tags"},
    )
    return b


def _enum_elem_builder(values: dict[str, int]) -> ProtoBuilder:
    """Isolated-pool builder: ``Container { repeated Elem elems = 1; }``, ``Elem { E status }``."""
    b = ProtoBuilder()
    b.message(
        "test.Elem",
        {"status": (T.TYPE_ENUM, 1, ".test.Elem.Status")},
        enums={"Status": values},
    )
    b.message_with_repeated(
        "test.Container",
        {"elems": (T.TYPE_MESSAGE, 1, ".test.Elem")},
        repeated_fields={"elems"},
    )
    return b


class TestU82CrossPoolEnumSetPairing:
    """U8-2: greedy first-fit set pairing over a non-transitive equality."""

    def test_pairs_cleanly_in_one_element_order_control(self) -> None:
        """Control: the engine itself treats these two multisets as fully pairable.

        ``[P(1), Q(5)]`` on the left and ``[Z(1), P(5)]`` on the right are the
        same multiset under the engine's own cross-pool enum equality
        (``P(1) ~ Z(1)`` and ``Q(5) ~ P(5)``, both by number), and in this
        element order the greedy scan finds that pairing. This is the reference
        answer the pin below asserts for the *other* order.
        """
        left = _enum_tags_builder(_LEFT_ENUM).build("test.Msg", tags=[1, 5])
        right = _enum_tags_builder(_RIGHT_ENUM).build("test.Msg", tags=[1, 5])

        d = MessageDifferencer()
        d.treat_as_set("tags")
        result = d.compare(left, right)

        assert not result.has_changes()

    def test_repeated_submessage_elements_pair_cleanly_in_one_order_control(self) -> None:
        """Control: the ``Container{repeated Elem}`` construction is valid and pairable.

        Same two-pool shape as the submessage pin below, in the element
        order the greedy scan happens to get right. It exists so that a
        construction failure -- a descriptor pool that cannot resolve
        ``Elem`` from ``Container`` (the pure-Python protobuf backend
        rejects ``ProtoBuilder``'s one-file-per-message layout) -- shows
        up as a RED control here rather than as a pin that never reached
        its assertion. The bare-enum control above cannot catch that,
        because it builds a single message.
        """
        left_b = _enum_elem_builder(_LEFT_ENUM)
        right_b = _enum_elem_builder(_RIGHT_ENUM)
        left_elem = left_b.get_message_class("test.Elem")
        right_elem = right_b.get_message_class("test.Elem")

        left = left_b.build("test.Container", elems=[left_elem(status=1), left_elem(status=5)])
        right = right_b.build("test.Container", elems=[right_elem(status=1), right_elem(status=5)])

        d = MessageDifferencer()
        d.treat_as_set("elems")
        result = d.compare(left, right)

        assert not result.has_changes()

    @pytest.mark.xfail(
        strict=True,
        raises=AssertionError,
        reason="U8-2: treat_as_set's greedy first-fit pairing over the non-transitive "
               "cross-pool enum relation (same name OR same number) is order-dependent — "
               "the same multiset reports a spurious REMOVED/ADDED pair in one element "
               "order and zero differences in the other; needs max-cardinality matching",
    )
    def test_same_multiset_in_the_other_order_must_still_compare_equal(self) -> None:
        """A reordered but identical multiset must still compare equal under ``treat_as_set``.

        User-visible consequence: two messages that hold the same set of enum
        values across an evolved schema compare EQUAL or UNEQUAL purely
        according to the order the elements happen to sit in on the wire. A
        ``treat_as_set`` assertion documented as order-independent therefore
        fails on data it passed a moment ago, reporting a value that is present
        on both sides as REMOVED and its counterpart as ADDED.

        Mechanism: ``left P(1)`` greedily claims ``right P(5)`` on the NAME
        match, which strands ``Q(5)`` and ``Z(1)`` even though the perfect
        matching ``P(1)~Z(1)`` + ``Q(5)~P(5)`` exists.
        """
        left = _enum_tags_builder(_LEFT_ENUM).build("test.Msg", tags=[1, 5])
        right = _enum_tags_builder(_RIGHT_ENUM).build("test.Msg", tags=[5, 1])

        d = MessageDifferencer()
        d.treat_as_set("tags")
        result = d.compare(left, right)

        observed = [(str(diff.path), diff.change_type.name) for diff in result]
        # Today: [('tags[1]', 'REMOVED'), ('tags[1]', 'ADDED')].
        assert observed == []

    @pytest.mark.xfail(
        strict=True,
        raises=AssertionError,
        reason="U8-2: the same order-dependent greedy pairing reached through ordinary "
               "repeated submessages — Elem{status} elements carrying cross-pool enums "
               "report a spurious elems[1].status REMOVED/ADDED pair in one order only",
    )
    def test_repeated_submessage_elements_must_pair_order_independently(self) -> None:
        """The defect is not confined to bare repeated enums.

        User-visible consequence: the far more ordinary shape — a repeated
        submessage carrying a status enum — inherits the same order-dependence,
        because message-element equality runs a sub-comparison that resolves
        the enum through the same cross-pool relation. A list of records
        compares equal or unequal based on element order alone.
        """
        left_b = _enum_elem_builder(_LEFT_ENUM)
        right_b = _enum_elem_builder(_RIGHT_ENUM)
        left_elem = left_b.get_message_class("test.Elem")
        right_elem = right_b.get_message_class("test.Elem")

        left = left_b.build("test.Container", elems=[left_elem(status=1), left_elem(status=5)])
        right = right_b.build("test.Container", elems=[right_elem(status=5), right_elem(status=1)])

        d = MessageDifferencer()
        d.treat_as_set("elems")
        result = d.compare(left, right)

        observed = [(str(diff.path), diff.change_type.name) for diff in result]
        # Today: [('elems[1].status', 'ADDED'), ('elems[1].status', 'REMOVED')].
        assert observed == []


# ---------------------------------------------------------------------------
# U8-3 — map key not representable in the other side's key type
# ---------------------------------------------------------------------------


def _map_builder(key_type: int) -> ProtoBuilder:
    """Isolated-pool builder: ``M { map<key_type, string> m = 1; }``."""
    b = ProtoBuilder()
    b.map_message("test.M", fields={}, map_fields={"m": (key_type, T.TYPE_STRING, 1)})
    return b


def _map_with_key(key_type: int, key: int) -> Message:
    """Build a ``test.M`` in its own pool holding a single entry ``{key: "x"}``."""
    msg = _map_builder(key_type).get_message_class("test.M")()
    msg.m[key] = "x"
    return msg


class TestU83MapKeyOutOfRangeAcrossPools:
    """U8-3: schema-compatible integer map keys crash the per-key membership test."""

    def test_widening_key_type_compares_normally_control(self) -> None:
        """Control: an int32 key of -1 against an int64-keyed map is compared, not rejected.

        ``-1`` IS representable as an int64 map key, so the same construction
        completes and reports the key difference. This isolates the pin below to
        representability, not to "the key types differ".
        """
        left = _map_with_key(T.TYPE_INT32, -1)
        right = _map_with_key(T.TYPE_INT64, 1)

        result = MessageDifferencer().compare(left, right)

        assert result.has_changes()

    def test_in_range_key_across_int_types_compares_equal_control(self) -> None:
        """Control: ``map<int32,string>`` vs ``map<uint32,string>`` is a SUPPORTED comparison.

        The key gate in ``_compare_map`` treats all integer types as compatible,
        so with an in-range key the two maps compare equal. The crash pinned
        below is therefore on a path the differ deliberately supports — this is
        not an unsupported schema change.
        """
        left = _map_with_key(T.TYPE_INT32, 1)
        right = _map_with_key(T.TYPE_UINT32, 1)

        result = MessageDifferencer().compare(left, right)

        assert not result.has_changes()

    @pytest.mark.parametrize(
        ("left_key_type", "left_key", "right_key_type", "right_key"),
        [
            pytest.param(T.TYPE_INT32, -1, T.TYPE_UINT32, 1, id="int32-neg-vs-uint32"),
            pytest.param(T.TYPE_UINT32, 2**32 - 1, T.TYPE_INT32, 1, id="uint32-max-vs-int32"),
            pytest.param(T.TYPE_INT64, 2**40, T.TYPE_INT32, 1, id="int64-wide-vs-int32"),
        ],
    )
    @pytest.mark.xfail(
        strict=True,
        raises=ValueError,
        reason="U8-3: a map key not representable in the other side's key type escapes "
               "_compare_map's key gate (_types_compatible calls all integer types "
               "compatible) and then raises ValueError: Value out of range out of the "
               "membership test — an undocumented CRASH on schema-compatible input",
    )
    def test_out_of_range_key_must_not_crash_compare(
        self,
        left_key_type: int,
        left_key: int,
        right_key_type: int,
        right_key: int,
    ) -> None:
        """Comparing two integer-keyed maps must return a diff, never raise.

        User-visible consequence: a schema evolution as ordinary as
        ``map<int32,string>`` → ``map<uint32,string>`` turns ``compare()`` into
        a traceback the moment real data carries a negative (or too-wide) key —
        the documented cross-schema CLI path (``protokit diff old.bin new.bin
        --left-desc v1.fds --right-desc v2.fds``) exits with an error instead of
        a report. ``compare()``'s own ``Raises:`` section promises only
        ``DuplicateKeyError`` and ``MissingKeyError``.

        A key that cannot be represented on the other side is simply absent
        there, so the correct outcome is the same removed/added pair any other
        unmatched key gets.
        """
        left = _map_with_key(left_key_type, left_key)
        right = _map_with_key(right_key_type, right_key)

        # Today this raises ValueError("Value out of range: ...") out of compare().
        result = MessageDifferencer().compare(left, right)

        assert result.has_changes()


# ---------------------------------------------------------------------------
# U8-4 — treat_as_map on a field that exists on only one schema
# ---------------------------------------------------------------------------


def _keyed_items_pool() -> ProtoBuilder:
    """v1 pool: ``Outer{Container c}``, ``Container{repeated Item items}``, ``Item{id,value}``."""
    b = ProtoBuilder()
    b.message("test.Item", {"id": (T.TYPE_STRING, 1), "value": (T.TYPE_INT32, 2)})
    b.message_with_repeated(
        "test.Container",
        {"items": (T.TYPE_MESSAGE, 1, ".test.Item")},
        repeated_fields={"items"},
    )
    b.message("test.Outer", {"c": (T.TYPE_MESSAGE, 1, ".test.Container")})
    return b


def _dropped_items_pool() -> ProtoBuilder:
    """v2 pool: the same message names with the repeated field DELETED."""
    b = ProtoBuilder()
    b.message("test.Container", {"note": (T.TYPE_STRING, 9)})
    b.message("test.Outer", {"note": (T.TYPE_STRING, 9)})
    return b


class TestU84TreatAsMapOnSchemaOnlyField:
    """U8-4: ``_emit_one_sided`` skips ``_extract_keys`` for a one-schema-only field.

    Counter-argument considered and rejected: ``treat_as_map``'s docstring says
    the field "must be a repeated message field on both sides", so one could
    read a one-schema-only field as out of contract. It does not excuse this
    behaviour. The engine's declared response to a ``treat_as_map`` selector it
    cannot honour is a ``Diagnostic`` plus documented index-comparison fallback
    (``_compare_repeated``); here there is no diagnostic and no fallback
    contract — just a silent divergence between two routes through the same
    situation, one of which (``_emit_all_fields``) keys the list and raises.
    """

    def test_duplicate_keys_raise_when_both_schemas_declare_the_field_control(self) -> None:
        """Control: the two-sided route enforces the documented key contract."""
        b = _keyed_items_pool()
        item = b.get_message_class("test.Item")
        left = b.build("test.Container", items=[item(id="dup", value=1), item(id="dup", value=2)])
        right = b.build("test.Container", items=[item(id="dup", value=1)])

        d = MessageDifferencer()
        d.treat_as_map("items", key="id")

        with pytest.raises(DuplicateKeyError):
            d.compare(left, right)

    def test_one_sided_subtree_route_keys_and_raises_control(self) -> None:
        """Control: the SIBLING one-sided route (``_emit_all_fields``) does key the list.

        Here the whole ``c`` subtree is left-only (the v2 ``Outer`` has no ``c``
        field), so the container is emitted through ``_emit_all_fields``, which
        derives keys through ``_extract_keys`` — duplicate keys raise, and
        unique keys produce ``c.items[id="a"].value`` paths. The two pins below
        assert the *other* one-sided route must behave the same way.
        """
        left_b = _keyed_items_pool()
        right_b = _dropped_items_pool()
        item = left_b.get_message_class("test.Item")

        unique = left_b.build(
            "test.Outer",
            c=left_b.build("test.Container", items=[item(id="a", value=1)]),
        )
        right = right_b.build("test.Outer", note="n")

        d = MessageDifferencer()
        d.treat_as_map("items", key="id")
        paths = [str(diff.path) for diff in d.compare(unique, right)]
        assert paths == ['c.items[id="a"].id', 'c.items[id="a"].value', "note"]

        duplicated = left_b.build(
            "test.Outer",
            c=left_b.build(
                "test.Container",
                items=[item(id="dup", value=1), item(id="dup", value=2)],
            ),
        )
        d2 = MessageDifferencer()
        d2.treat_as_map("items", key="id")
        with pytest.raises(DuplicateKeyError):
            d2.compare(duplicated, right)

    @pytest.mark.xfail(
        strict=True,
        raises=pytest.fail.Exception,
        reason="U8-4: a treat_as_map field present on only one schema takes "
               "_emit_one_sided's plain repeated branch, which never calls "
               "_extract_keys, so duplicate keys are emitted silently instead of "
               "raising the DuplicateKeyError compare() documents unconditionally",
    )
    def test_duplicate_keys_on_a_deleted_field_must_raise(self) -> None:
        """Duplicate keys must be reported whichever side declares the field.

        User-visible consequence: deleting a repeated field between schema
        versions — the differ's core use case — silently disables the
        ``treat_as_map`` key validation for that field. Data that would be
        rejected as malformed while both versions declared the field is
        accepted the moment the field is dropped, so the release that removes
        the field is exactly the one that stops catching duplicate keys.

        ``compare()``'s ``Raises:`` section states the error unconditionally
        ("duplicate keys in ONE side's elements"), and the sibling one-sided
        route pinned in the control above raises it.
        """
        left_b = _keyed_items_pool()
        right_b = _dropped_items_pool()
        item = left_b.get_message_class("test.Item")
        left = left_b.build(
            "test.Container",
            items=[item(id="dup", value=1), item(id="dup", value=2)],
        )
        right = right_b.build("test.Container", note="n")

        d = MessageDifferencer()
        d.treat_as_map("items", key="id")

        # Today: no error; emits items[0].* and items[1].* REMOVED leaves.
        with pytest.raises(DuplicateKeyError):
            d.compare(left, right)

    @pytest.mark.xfail(
        strict=True,
        raises=AssertionError,
        reason="U8-4: the same _extract_keys bypass in _emit_one_sided also emits index "
               "paths (items[0].value) for a deleted treat_as_map field where every other "
               "route emits key paths (items[id=\"a\"].value)",
    )
    def test_deleted_field_elements_must_keep_their_key_paths(self) -> None:
        """A ``treat_as_map`` field must keep its key paths when the field is deleted.

        User-visible consequence: the REMOVED entries for a deleted keyed list
        are addressed by position (``items[0].value``) instead of by key
        (``items[id="a"].value``), so downstream consumers that match on the
        documented ``field[key="..."]`` path form — ignore selectors, report
        filters, diffs pasted between versions — silently stop matching for
        exactly the fields that were deleted.
        """
        left_b = _keyed_items_pool()
        right_b = _dropped_items_pool()
        item = left_b.get_message_class("test.Item")
        left = left_b.build("test.Container", items=[item(id="a", value=1)])
        right = right_b.build("test.Container", note="n")

        d = MessageDifferencer()
        d.treat_as_map("items", key="id")
        paths = [str(diff.path) for diff in d.compare(left, right)]

        # Today: ['items[0].id', 'items[0].value', 'note'].
        assert paths == ['items[id="a"].id', 'items[id="a"].value', "note"]


# ---------------------------------------------------------------------------
# U8-5 — a deeper dotted ignore selector evades the treat_as_map key guard
# ---------------------------------------------------------------------------


def _outer_items_pool() -> ProtoBuilder:
    """``Outer { Container container }``, ``Container { repeated Item items }``, ``Item { id }``.

    ``id`` is the element's ONLY field, so ignoring it erases the element.
    """
    b = ProtoBuilder()
    b.message("test.Item", {"id": (T.TYPE_STRING, 1)})
    b.message_with_repeated(
        "test.Container",
        {"items": (T.TYPE_MESSAGE, 1, ".test.Item")},
        repeated_fields={"items"},
    )
    b.message("test.Outer", {"container": (T.TYPE_MESSAGE, 1, ".test.Container")})
    return b


def _outer_with_item(builder: ProtoBuilder, item_id: str) -> Message:
    """Build ``Outer{container{items:[Item{id: item_id}]}}`` from ``builder``'s pool."""
    return builder.build(
        "test.Outer",
        container=builder.build(
            "test.Container",
            items=[builder.build("test.Item", id=item_id)],
        ),
    )


class TestU85IgnoreEvadesTreatAsMapKeyGuard:
    """U8-5: the key-conflict guard matches only the bare ``<map_sel>.<key>`` spelling."""

    def test_map_is_in_force_at_the_nested_path_control(self) -> None:
        """Control: ``treat_as_map('items')`` really does apply at ``container.items``.

        The bracketed baseline paths prove the conflict the guard is supposed to
        catch is a genuine conflict at ``container.items.id``, not a selector
        that happens to name an unrelated field.
        """
        b = _outer_items_pool()
        d = MessageDifferencer()
        d.treat_as_map("items", key="id")
        result = d.compare(_outer_with_item(b, "a"), _outer_with_item(b, "b"))

        assert [(str(diff.path), diff.change_type) for diff in result] == [
            ('container.items[id="a"].id', ChangeType.REMOVED),
            ('container.items[id="b"].id', ChangeType.ADDED),
        ]

    @pytest.mark.parametrize("selector", ["id", "items.id"])
    def test_guarded_spellings_of_the_key_field_are_rejected_control(self, selector: str) -> None:
        """Control: the two spellings the guard does recognise raise at registration."""
        d = MessageDifferencer()
        d.treat_as_map("items", key="id")

        with pytest.raises(ValueError, match="treat_as_map"):
            d.ignore_fields(selector)

    @pytest.mark.parametrize(
        "ignore_first", [False, True], ids=["map-then-ignore", "ignore-then-map"],
    )
    @pytest.mark.xfail(
        strict=True,
        raises=pytest.fail.Exception,
        reason="U8-5: the treat_as_map key-conflict guard compares only the exact "
               "f'{map_sel}.{key_name}' spelling, so the fully qualified "
               "'container.items.id' — the same key field of the same in-force map — is "
               "accepted in either registration order instead of raising ValueError",
    )
    def test_fully_qualified_key_selector_must_be_rejected(self, ignore_first: bool) -> None:
        """A deeper dotted path naming the map key must be rejected like the short forms.

        User-visible consequence: the guard that exists to stop a caller from
        deleting the key its own ``treat_as_map`` runs on is bypassed by writing
        the key's full path. The caller gets no error, and the comparison then
        silently reports different messages as equal (pinned below).

        ``ignore_fields``' docstring states that conflict validation with
        ``treat_as_map`` is enforced at registration "for the string forms
        only" — only the opaque predicate form is exempt — and its ``Raises:``
        names exactly this case ("e.g. ignoring a map key field"). The remedy is
        to widen the guard, not to redefine the compare-time behaviour.
        """
        d = MessageDifferencer()

        with pytest.raises(ValueError, match="treat_as_map"):
            if ignore_first:
                d.ignore_fields("container.items.id")
                d.treat_as_map("items", key="id")
            else:
                d.treat_as_map("items", key="id")
                d.ignore_fields("container.items.id")

    @pytest.mark.xfail(
        strict=True,
        raises=AssertionError,
        reason="U8-5: once the evaded ignore erases the element's only populated field, "
               "two messages differing in exactly that field compare EQUAL — "
               "has_changes() is False with an empty diff list",
    )
    def test_evaded_ignore_must_not_report_different_messages_as_equal(self) -> None:
        """The consequence of the evasion: a silent false EQUAL.

        User-visible consequence: ``Outer{container{items:[{id:"a"}]}}`` and
        ``Outer{container{items:[{id:"b"}]}}`` are reported as identical. An
        assertion built on this configuration passes on data it should reject —
        the worst failure mode a differ has, because nothing is printed.

        This flips under either legitimate remedy: rejecting the selector at
        registration (the pin above) short-circuits here, and keeping the key
        alive at compare time makes the difference reappear.
        """
        b = _outer_items_pool()
        d = MessageDifferencer()
        d.treat_as_map("items", key="id")
        try:
            d.ignore_fields("container.items.id")
        except ValueError:
            # Registration now rejects the evasion, so the false EQUAL below
            # cannot arise: the finding is fixed.
            return

        result = d.compare(_outer_with_item(b, "a"), _outer_with_item(b, "b"))

        # Today: has_changes() is False and the diff list is empty.
        assert result.has_changes()


# ===========================================================================
# Deferred V-series findings owned by a later release (V28, V18, V5)
# ===========================================================================
#
# These three were found by the whole-codebase audit
# (``docs/plans/AUDIT-whole-codebase-2026-08-30.md``) and reproduced again,
# unpinned, by the cycle-1 re-audit (``docs/plans/AUDIT-cycle-1-2026-09-27.md``,
# rows R13-C6, R13-X1/C5 and R05-X1). The stability release plan assigns each
# to a 0.17.0 unit. The pins below are strict, each ``reason`` leads with the
# finding ID and names the owning unit and release, and each pin flips to XPASS
# (a hard failure) the day its mechanism is fixed. Every control shares its
# pin's construction and asserts behaviour that stays correct after the fix.
#
# * V28 (U10, 0.17.0) — ``_set_elements_equal`` decides message-element
#   equality with a fresh default-config ``MessageDifferencer()``, so the
#   caller's ``ignore_fields`` is dropped inside ``treat_as_set`` pairing.
#   Elements that differ only in an ignored field fail to pair, and the
#   difference is reported on a field that did not change.
# * V18 (U10, 0.17.0) — ``compare()`` walks declared fields only and never
#   reads either side's unknown-field set. Two messages that differ only in
#   bytes the reader's schema does not declare give no difference and no
#   diagnostic, and ``protokit diff`` with a stale ``--desc`` prints
#   "Messages are equal." and exits 0. The pins assert what U10 delivers: a
#   diagnostic whenever unknown fields are present. Whether the differences
#   themselves are reported stays opt-in under that unit, so the pins do not
#   assert on ``has_changes()`` or the exit code.
#   ``tests/meta/test_doc_claims.py`` measures today's output as a guard on
#   the 0.16.0 prose; these are its strict-xfail counterpart.
# * V5 (U14b, 0.17.0) — ``_is_default_value`` compares a field's value to
#   ``fd.default_value`` with ``==``. ``nan == nan`` is False, so a proto2
#   field set explicitly to its declared ``[default = nan]`` never collapses
#   as a default in EQUIVALENT presence mode.


def _observed(result: DiffResult) -> list[tuple[str, str]]:
    """The result's differences as ``(path, change type name)`` pairs."""
    return [(str(diff.path), diff.change_type.name) for diff in result]


def _message_class(file_proto: descriptor_pb2.FileDescriptorProto) -> type[Message]:
    """The class of ``<package>.M`` from ``file_proto``, built in its own pool."""
    pool = descriptor_pool.DescriptorPool()
    pool.Add(file_proto)
    descriptor = pool.FindMessageTypeByName(f"{file_proto.package}.M")
    return message_factory.GetMessageClass(descriptor)


# ---------------------------------------------------------------------------
# V28 — treat_as_set drops the caller's ignore_fields
# ---------------------------------------------------------------------------


def _noisy_items_pool() -> ProtoBuilder:
    """``Outer { repeated Item items }``, ``Item { id, noise }``."""
    b = ProtoBuilder()
    b.message("test.Item", {"id": (T.TYPE_STRING, 1), "noise": (T.TYPE_STRING, 2)})
    b.message_with_repeated(
        "test.Outer",
        {"items": (T.TYPE_MESSAGE, 1, ".test.Item")},
        repeated_fields={"items"},
    )
    return b


def _noisy_outer(builder: ProtoBuilder, *items: tuple[str, str]) -> Message:
    """Build ``Outer`` holding one ``Item(id, noise)`` per ``(id, noise)`` pair."""
    item = builder.get_message_class("test.Item")
    return builder.build(
        "test.Outer",
        items=[item(id=item_id, noise=noise) for item_id, noise in items],
    )


class TestV28TreatAsSetDropsIgnoreFields:
    """V28: set pairing compares elements with a differ that has no configuration."""

    def test_ignore_alone_hides_the_noise_field_control(self) -> None:
        """Control: under index pairing ``ignore_fields("noise")`` is honoured.

        Unconfigured, the one element's ``noise`` is the only difference; with
        the ignore it is gone. This is the reference answer the pin asserts
        for the same data once ``treat_as_set`` is also configured.
        """
        b = _noisy_items_pool()
        left = _noisy_outer(b, ("a", "x"))
        right = _noisy_outer(b, ("a", "y"))

        assert _observed(MessageDifferencer().compare(left, right)) == [
            ("items[0].noise", "MODIFIED"),
        ]

        d = MessageDifferencer()
        d.ignore_fields("noise")
        assert _observed(d.compare(left, right)) == []

    def test_set_pairing_with_an_ignore_pairs_identical_elements_control(self) -> None:
        """Control: ``treat_as_set`` plus ``ignore_fields`` is a supported configuration.

        With both registered, the same elements in a different order pair up
        and compare equal. So the two policies coexist on this construction,
        and the pin's failure is specific to elements that differ in the
        ignored field.
        """
        b = _noisy_items_pool()
        left = _noisy_outer(b, ("a", "x"), ("b", "y"))
        right = _noisy_outer(b, ("b", "y"), ("a", "x"))

        d = MessageDifferencer()
        d.ignore_fields("noise")
        d.treat_as_set("items")

        assert _observed(d.compare(left, right)) == []

    @pytest.mark.parametrize("set_first", [False, True], ids=["ignore-then-set", "set-then-ignore"])
    @pytest.mark.xfail(
        strict=True,
        raises=AssertionError,
        reason="V28: owned by U10 (0.17.0). _set_elements_equal decides message-element "
               "equality with a fresh default-config MessageDifferencer(), so the caller's "
               "ignore_fields is dropped inside treat_as_set pairing: elements that differ "
               "only in the ignored field fail to pair, and the unchanged items[0].id is "
               "reported as both ADDED and REMOVED",
    )
    def test_ignored_field_must_stay_ignored_under_set_pairing(self, set_first: bool) -> None:
        """``ignore_fields`` plus ``treat_as_set`` must equal ``ignore_fields`` alone here.

        User-visible consequence: the same configuration and the same data
        give opposite answers depending on how the list is paired. Adding
        ``treat_as_set("items")`` to a differ that already ignores ``noise``
        turns an equal comparison into a failing one, and the reported paths
        name ``items[0].id`` — the field that did not change — rather than the
        ignored field that did.
        """
        b = _noisy_items_pool()
        left = _noisy_outer(b, ("a", "x"))
        right = _noisy_outer(b, ("a", "y"))

        d = MessageDifferencer()
        if set_first:
            d.treat_as_set("items")
            d.ignore_fields("noise")
        else:
            d.ignore_fields("noise")
            d.treat_as_set("items")

        # Today: [('items[0].id', 'ADDED'), ('items[0].id', 'REMOVED')].
        assert _observed(d.compare(left, right)) == []


# ---------------------------------------------------------------------------
# V18 — a difference only in unknown fields is a silent EQUAL
# ---------------------------------------------------------------------------

# The reader's schema is one version behind the writer's: the writer added
# ``amount`` (field 2), which the old schema does not declare.
_OLD_FIELDS = {"id": (T.TYPE_INT32, 1)}
_NEW_FIELDS = {"id": (T.TYPE_INT32, 1), "amount": (T.TYPE_INT64, 2)}


def _schema_file(fields: dict[str, tuple[int, int]]) -> descriptor_pb2.FileDescriptorProto:
    """A proto3 file declaring ``test.M`` with ``fields`` (name -> (type, number))."""
    file_proto = descriptor_pb2.FileDescriptorProto(
        name="m.proto", package="test", syntax="proto3",
    )
    msg = file_proto.message_type.add(name="M")
    for name, (field_type, number) in fields.items():
        msg.field.add(name=name, number=number, type=field_type, label=T.LABEL_OPTIONAL)
    return file_proto


def _payloads(*, amounts: tuple[int, int]) -> tuple[bytes, bytes]:
    """Two payloads written with the NEW schema: same ``id``, the given ``amount`` each."""
    new_cls = _message_class(_schema_file(_NEW_FIELDS))
    left, right = (new_cls(id=1, amount=amount).SerializeToString() for amount in amounts)
    return left, right


def _read_with(
    fields: dict[str, tuple[int, int]], payloads: tuple[bytes, bytes],
) -> tuple[Message, Message]:
    """Parse both payloads with a reader whose schema declares ``fields``."""
    cls = _message_class(_schema_file(fields))
    return cls.FromString(payloads[0]), cls.FromString(payloads[1])


def _run_diff_cli(
    tmp_path: Path,
    fields: dict[str, tuple[int, int]],
    payloads: tuple[bytes, bytes],
    *options: str,
) -> tuple[int, str]:
    """Run ``protokit diff`` on ``payloads`` with a descriptor set declaring ``fields``.

    Returns ``(exit code, stdout)``. ``catch_exceptions=False`` so a crash
    surfaces as itself instead of as Click's exit 1.
    """
    descriptor_set = descriptor_pb2.FileDescriptorSet(file=[_schema_file(fields)])
    desc = tmp_path / "schema.desc"
    desc.write_bytes(descriptor_set.SerializeToString())
    left, right = tmp_path / "left.bin", tmp_path / "right.bin"
    left.write_bytes(payloads[0])
    right.write_bytes(payloads[1])

    result = CliRunner().invoke(
        diff_main,
        [str(left), str(right), "--desc", str(desc), "--message-type", "test.M", *options],
        catch_exceptions=False,
    )
    return result.exit_code, result.stdout


class TestV18UnknownFieldOnlyDifferenceIsSilent:
    """V18: the differ never reads unknown fields and says nothing about them."""

    def test_stale_reader_keeps_the_differing_bytes_as_unknown_fields_control(self) -> None:
        """Control: the two messages really do differ, in bytes the reader kept.

        Both backends retain an undeclared field in the unknown-field set and
        write it back out, and protobuf's own ``==`` sees the difference. A
        backend that dropped the bytes at parse time would make the pins below
        vacuous; this goes red first.
        """
        left, right = _read_with(_OLD_FIELDS, _payloads(amounts=(100, 999)))

        assert left.id == right.id == 1
        assert left.SerializeToString() != right.SerializeToString()
        assert left != right

    def test_reader_that_declares_the_field_reports_the_difference_control(self) -> None:
        """Control: with the current schema the same payloads differ at ``amount``.

        No diagnostic accompanies it, so a diagnostic in the pin below can
        only be about the unknown fields.
        """
        left, right = _read_with(_NEW_FIELDS, _payloads(amounts=(100, 999)))

        result = MessageDifferencer().compare(left, right)

        assert _observed(result) == [("amount", "MODIFIED")]
        assert list(result.diagnostics) == []

    def test_messages_without_unknown_fields_get_no_diagnostic_control(self) -> None:
        """Control: equal messages whose every field the reader declares stay silent.

        The new-schema reader declares ``amount``, so nothing is unknown, and
        an equal pair gives no difference and no diagnostic. This stays true
        after the fix: the diagnostic is for unknown fields, not for every run.
        """
        left, right = _read_with(_NEW_FIELDS, _payloads(amounts=(100, 100)))

        result = MessageDifferencer().compare(left, right)

        assert not result.has_changes()
        assert list(result.diagnostics) == []

    @pytest.mark.xfail(
        strict=True,
        raises=AssertionError,
        reason="V18: owned by U10 (0.17.0). compare() walks declared fields only and never "
               "reads either side's unknown-field set, so two messages that differ only in "
               "bytes the reader's schema does not declare give no difference AND no "
               "diagnostic — a silent EQUAL",
    )
    def test_unknown_field_only_difference_must_emit_a_diagnostic(self) -> None:
        """A comparison that skipped unknown fields must say so.

        User-visible consequence: a consumer one schema version behind
        compares two payloads whose ``amount`` is 100 and 999 and is told they
        are identical — ``has_changes()`` is False, ``diagnostics`` is empty —
        while protobuf's own ``==`` says they differ. Nothing in the result
        lets the caller learn that bytes went uncompared.

        U10 emits a diagnostic whenever either side carries unknown fields and
        keeps reporting the differences themselves opt-in, so this pin asserts
        the diagnostic only.
        """
        left, right = _read_with(_OLD_FIELDS, _payloads(amounts=(100, 999)))

        result = MessageDifferencer().compare(left, right)

        # Today: no differences and diagnostics == ().
        assert list(result.diagnostics) != []

    def test_diff_cli_with_the_current_schema_reports_the_difference_control(
        self, tmp_path: Path
    ) -> None:
        """Control: ``protokit diff`` reads these files and finds ``amount`` when it can.

        Given a descriptor set that declares ``amount``, the JSON report names
        the difference with an empty ``diagnostics`` list and the command
        exits 1. The human report under ``--verbose`` names it too.
        """
        payloads = _payloads(amounts=(100, 999))

        exit_code, stdout = _run_diff_cli(tmp_path, _NEW_FIELDS, payloads, "--format", "json")
        report = json.loads(stdout)
        assert exit_code == 1
        assert [diff["path"] for diff in report["differences"]] == ["amount"]
        assert report["diagnostics"] == []

        exit_code, stdout = _run_diff_cli(tmp_path, _NEW_FIELDS, payloads, "--verbose")
        assert exit_code == 1
        assert "amount" in stdout

    def test_diff_cli_bare_equal_verdict_without_unknown_fields_control(
        self, tmp_path: Path
    ) -> None:
        """Control: with nothing unknown, ``--verbose`` prints the bare verdict, rightly.

        Equal payloads read with a schema that declares every field have no
        warning to show, so "Messages are equal." alone is the correct output
        and stays correct after the fix.
        """
        payloads = _payloads(amounts=(100, 100))

        exit_code, stdout = _run_diff_cli(tmp_path, _NEW_FIELDS, payloads, "--verbose")

        assert (exit_code, stdout) == (0, "Messages are equal.\n")

    @pytest.mark.xfail(
        strict=True,
        raises=AssertionError,
        reason="V18: owned by U10 (0.17.0). The same silent EQUAL through `protokit diff` "
               "with a stale --desc: the differ records nothing about the unknown fields, "
               "so --format json reports equal true and complete true with an EMPTY "
               "diagnostics list for payloads whose amount is 100 vs 999",
    )
    def test_diff_cli_json_must_carry_a_diagnostic_for_a_stale_schema(
        self, tmp_path: Path
    ) -> None:
        """The JSON report must record that unknown fields were present.

        User-visible consequence: a CI job that diffs two payloads against a
        descriptor set one version old gets ``"equal": true, "complete":
        true, "diagnostics": []`` and exit 0. Every field a consumer could
        gate on says the run was whole and the payloads match.
        """
        payloads = _payloads(amounts=(100, 999))

        _exit_code, stdout = _run_diff_cli(tmp_path, _OLD_FIELDS, payloads, "--format", "json")

        # Today: "diagnostics": [].
        assert json.loads(stdout)["diagnostics"] != []

    @pytest.mark.xfail(
        strict=True,
        raises=AssertionError,
        reason="V18: owned by U10 (0.17.0). `protokit diff --verbose` exists to show "
               "warnings on an equal result, but with a stale --desc the differ records "
               "nothing about the unknown fields, so the whole output is the bare verdict "
               "'Messages are equal.' for payloads whose amount is 100 vs 999",
    )
    def test_diff_cli_verbose_must_not_print_a_bare_equal_verdict_for_a_stale_schema(
        self, tmp_path: Path
    ) -> None:
        """``--verbose`` must show something beyond "Messages are equal." here.

        User-visible consequence: the person at the terminal asks for warnings
        as well as the verdict and is shown the verdict alone, in green, for
        two payloads that differ.
        """
        payloads = _payloads(amounts=(100, 999))

        _exit_code, stdout = _run_diff_cli(tmp_path, _OLD_FIELDS, payloads, "--verbose")

        # Today: exactly "Messages are equal.\n", exit 0. The warning has to be
        # about the unknown fields; a reworded verdict alone is not the fix.
        assert "unknown" in stdout.lower(), stdout


# ---------------------------------------------------------------------------
# V5 — a proto2 [default = nan] never collapses as a default
# ---------------------------------------------------------------------------


def _proto2_double_with_default(default: str) -> type[Message]:
    """proto2 ``M { optional double x = 1 [default = <default>]; }`` in its own pool."""
    file_proto = descriptor_pb2.FileDescriptorProto(
        name="m.proto", package="test", syntax="proto2",
    )
    file_proto.message_type.add(name="M").field.add(
        name="x",
        number=1,
        type=T.TYPE_DOUBLE,
        label=T.LABEL_OPTIONAL,
        default_value=default,
    )
    return _message_class(file_proto)


class TestV5NanDefaultNeverCollapses:
    """V5: the set-to-default test is ``==``, which NaN never satisfies."""

    @pytest.mark.parametrize("set_on_left", [True, False], ids=["set-on-left", "set-on-right"])
    def test_finite_default_set_explicitly_collapses_control(self, set_on_left: bool) -> None:
        """Control: a field set explicitly to a FINITE declared default equals unset.

        Same proto2 construction with ``[default = 1.5]``: the field has
        presence on one side only, and the default EQUIVALENT mode collapses
        it. This is the behaviour the pin asks for when the default is NaN.
        """
        cls = _proto2_double_with_default("1.5")
        explicit, unset = cls(x=1.5), cls()
        assert explicit.HasField("x")
        assert not unset.HasField("x")

        left, right = (explicit, unset) if set_on_left else (unset, explicit)

        assert _observed(MessageDifferencer().compare(left, right)) == []

    def test_nan_default_is_declared_and_other_values_are_still_reported_control(self) -> None:
        """Control: the NaN default is real, and collapse is not "report nothing".

        The descriptor's default and the unset field's value are both NaN on
        this backend. A NON-default value against unset is reported, and so is
        the explicit NaN once the caller opts in to
        ``MessageFieldComparison.EQUAL``. Both stay true after the fix.
        """
        cls = _proto2_double_with_default("nan")
        assert math.isnan(cls.DESCRIPTOR.fields_by_name["x"].default_value)
        assert math.isnan(cls().x)

        assert _observed(MessageDifferencer().compare(cls(), cls(x=2.0))) == [("x", "ADDED")]

        strict_presence = MessageDifferencer()
        strict_presence.set_message_field_comparison(MessageFieldComparison.EQUAL)
        assert _observed(strict_presence.compare(cls(), cls(x=math.nan))) == [("x", "ADDED")]

    @pytest.mark.parametrize("set_on_left", [True, False], ids=["set-on-left", "set-on-right"])
    @pytest.mark.xfail(
        strict=True,
        raises=AssertionError,
        reason="V5: owned by U14b (0.17.0). _is_default_value compares the field's value "
               "to fd.default_value with ==, and nan == nan is False, so a proto2 double "
               "set explicitly to its declared [default = nan] never collapses in "
               "EQUIVALENT presence mode and is reported as REMOVED/ADDED against unset",
    )
    def test_nan_default_set_explicitly_must_collapse(self, set_on_left: bool) -> None:
        """A field set to its own declared NaN default must equal the unset field.

        User-visible consequence: EQUIVALENT mode promises that set-to-default
        and unset compare equal, and keeps that promise for every default
        except NaN. A writer that sets the field explicitly and one that
        leaves it unset produce messages the differ reports as different,
        although both read back the same value.
        """
        cls = _proto2_double_with_default("nan")
        explicit, unset = cls(x=math.nan), cls()

        left, right = (explicit, unset) if set_on_left else (unset, explicit)

        # Today: [('x', 'REMOVED')] with the field set on the left, [('x', 'ADDED')] on the right.
        assert _observed(MessageDifferencer().compare(left, right)) == []
