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
"""

from __future__ import annotations

import pytest
from google.protobuf import descriptor_pb2
from google.protobuf.message import Message

from protokit.message import ChangeType, DuplicateKeyError, MessageDifferencer
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

    @pytest.mark.xfail(
        strict=True,
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
