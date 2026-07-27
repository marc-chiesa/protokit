"""Tests for partial / sub-shape comparison scope (U4, R5, KTD-11).

Partial matching is **directional**: ``compare(left, right)`` treats ``left`` as
the expected side and ``right`` as the actual side. With ``set_partial()``:

* a field (or whole sub-message) present ONLY on the actual (right) side — an
  ADDED difference in full mode — is suppressed (extra fields on actual are not
  differences);
* a field present on expected (left) but MISSING on actual — a REMOVED
  difference — is STILL reported (directional, R5);
* a field present on both whose values DIFFER is STILL reported.

The rule recurses into nested messages present on the expected side.

``treat_as_set`` carve-out (KTD-8): partial does NOT descend into a set field —
set-element equality stays strict, so a set element present only on the actual
side is still reported even under partial.

Each behavioral test follows baseline-then-mechanism: first assert the
extra/removed/differing field DOES produce a difference in full mode (the proxy
signal is real), then assert partial changes (or does not change) the outcome —
so suppression is non-vacuous.
"""

from __future__ import annotations

from google.protobuf import descriptor_pb2

from protokit.message import ChangeType, MessageDifferencer
from tests.proto_builder import ProtoBuilder

T = descriptor_pb2.FieldDescriptorProto


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _user_builder() -> ProtoBuilder:
    """Flat message ``User{name, email, id}`` (all singular scalars)."""
    b = ProtoBuilder()
    b.message(
        "test.User",
        {
            "name": (T.TYPE_STRING, 1),
            "email": (T.TYPE_STRING, 2),
            "id": (T.TYPE_INT32, 3),
        },
    )
    return b


def _nested_builder() -> ProtoBuilder:
    """``Envelope{header: Header}`` where ``Header{version, note}``."""
    b = ProtoBuilder()
    b.message(
        "test.Header",
        {
            "version": (T.TYPE_INT32, 1),
            "note": (T.TYPE_STRING, 2),
        },
    )
    b.message(
        "test.Envelope",
        {"header": (T.TYPE_MESSAGE, 1, ".test.Header")},
    )
    return b


def _two_sub_builder() -> ProtoBuilder:
    """``Envelope{a: Sub, b: Sub}`` for whole-sub-message presence tests."""
    b = ProtoBuilder()
    b.message(
        "test.Sub",
        {"value": (T.TYPE_INT32, 1)},
    )
    b.message(
        "test.Envelope",
        {
            "a": (T.TYPE_MESSAGE, 1, ".test.Sub"),
            "b": (T.TYPE_MESSAGE, 2, ".test.Sub"),
        },
    )
    return b


def _set_elem_builder() -> ProtoBuilder:
    """``Container{items: repeated Item}`` where ``Item{id, value}``."""
    b = ProtoBuilder()
    b.message(
        "test.Item",
        {
            "id": (T.TYPE_STRING, 1),
            "value": (T.TYPE_INT32, 2),
        },
    )
    b.message_with_repeated(
        "test.Container",
        {"items": (T.TYPE_MESSAGE, 1, ".test.Item")},
        repeated_fields={"items"},
    )
    return b


def _set_scalar_builder() -> ProtoBuilder:
    """``Msg{tags: repeated string}`` for scalar-set carve-out test."""
    b = ProtoBuilder()
    b.message_with_repeated(
        "test.Msg",
        {"tags": (T.TYPE_STRING, 1)},
        repeated_fields={"tags"},
    )
    return b


def _map_builder() -> ProtoBuilder:
    """``M{labels: map<string,string>}`` for partial map-extra tests."""
    b = ProtoBuilder()
    b.map_message(
        "test.M",
        {},
        {"labels": (T.TYPE_STRING, T.TYPE_STRING, 1)},
    )
    return b


def _opt_builder() -> ProtoBuilder:
    """``Opt{flag: optional int32}`` (proto3 explicit presence)."""
    b = ProtoBuilder()
    b.message(
        "test.Opt",
        {"flag": (T.TYPE_INT32, 1)},
        optional_fields={"flag"},
    )
    return b


# ---------------------------------------------------------------------------
# AE1: extra fields on actual suppressed under partial
# ---------------------------------------------------------------------------


class TestExtraActualFieldsSuppressed:
    def test_extra_actual_fields_suppressed_baseline_full_reports(self) -> None:
        """expected{name}, actual{name,email,id} (name equal): partial passes.

        Baseline: full mode reports email + id as MODIFIED — proto3 implicit
        scalars have no presence bit, so default(expected)->value(actual) is a
        modify, not an add.
        """
        b = _user_builder()
        expected = b.build("test.User", name="Alice")
        actual = b.build("test.User", name="Alice", email="a@x.com", id=7)

        # Baseline: full mode reports the two extra actual fields as MODIFIED.
        full = MessageDifferencer().compare(expected, actual)
        assert full.has_changes()
        modified = {str(d.path) for d in full if d.change_type == ChangeType.MODIFIED}
        assert modified == {"email", "id"}

        # Mechanism: partial suppresses the actual-only fields -> equal.
        d = MessageDifferencer()
        d.set_partial()
        result = d.compare(expected, actual)
        assert not result.has_changes()

    def test_partial_value_diff_still_fails(self) -> None:
        """A field present on expected but DIFFERING still reports under partial."""
        b = _user_builder()
        expected = b.build("test.User", name="Alice")
        actual = b.build("test.User", name="Bob", email="b@x.com")

        # Baseline (full): name differs (MODIFIED) + email actual-only (ADDED).
        full = MessageDifferencer().compare(expected, actual)
        assert full.has_changes()

        # Partial: email suppressed, but the name value diff still reports.
        d = MessageDifferencer()
        d.set_partial()
        result = d.compare(expected, actual)
        assert result.has_changes()
        modified = [m for m in result if m.change_type == ChangeType.MODIFIED]
        assert [str(m.path) for m in modified] == ["name"]
        # No ADDED leaked through for the actual-only email.
        assert [a for a in result if a.change_type == ChangeType.ADDED] == []

    def test_partial_missing_on_actual_still_removed(self) -> None:
        """A sub-message on expected but MISSING on actual is still REMOVED (directional).

        Uses a message field (genuine presence) so the absence is a real
        one-sided REMOVED; a proto3 implicit scalar would instead surface as a
        default-valued MODIFIED (covered by the value-diff test).
        """
        b = _nested_builder()
        # expected has a header; actual has none -> header is expected-only.
        expected = b.build("test.Envelope", header=b.build("test.Header", version=2))
        actual = b.build("test.Envelope")

        # Baseline (full): the header subtree reports as REMOVED (expected-only).
        full = MessageDifferencer().compare(expected, actual)
        removed_full = {str(r.path) for r in full if r.change_type == ChangeType.REMOVED}
        assert removed_full  # e.g. {"header.version"}

        # Partial: REMOVED is directional and NOT suppressed.
        d = MessageDifferencer()
        d.set_partial()
        result = d.compare(expected, actual)
        removed = {str(r.path) for r in result if r.change_type == ChangeType.REMOVED}
        assert removed == removed_full


# ---------------------------------------------------------------------------
# Nested partial: recursion into sub-messages present on expected
# ---------------------------------------------------------------------------


class TestNestedPartial:
    def test_nested_extra_actual_fields_suppressed(self) -> None:
        """expected{header{version}} ignores other header fields on actual."""
        b = _nested_builder()
        expected = b.build(
            "test.Envelope", header=b.build("test.Header", version=2),
        )
        actual = b.build(
            "test.Envelope",
            header=b.build("test.Header", version=2, note="hello"),
        )

        # Baseline (full): header.note (proto3 scalar) is default->value, i.e.
        # MODIFIED, not ADDED.
        full = MessageDifferencer().compare(expected, actual)
        modified_full = {
            str(d.path) for d in full if d.change_type == ChangeType.MODIFIED
        }
        assert modified_full == {"header.note"}

        # Partial recurses: the nested actual-only field is suppressed.
        d = MessageDifferencer()
        d.set_partial()
        result = d.compare(expected, actual)
        assert not result.has_changes()

    def test_nested_value_diff_still_fails(self) -> None:
        """A nested field present on expected but differing still reports."""
        b = _nested_builder()
        expected = b.build(
            "test.Envelope", header=b.build("test.Header", version=2),
        )
        actual = b.build(
            "test.Envelope",
            header=b.build("test.Header", version=9, note="extra"),
        )

        d = MessageDifferencer()
        d.set_partial()
        result = d.compare(expected, actual)
        modified = [m for m in result if m.change_type == ChangeType.MODIFIED]
        assert [str(m.path) for m in modified] == ["header.version"]
        # note (actual-only) is suppressed.
        assert [a for a in result if a.change_type == ChangeType.ADDED] == []

    def test_whole_actual_only_submessage_suppressed(self) -> None:
        """A whole sub-message present only on actual is suppressed under partial.

        ``b`` is set on actual but not expected; in full mode the entire ``b``
        subtree reports as ADDED. Partial must suppress it BEFORE the separate
        recursive walk runs.
        """
        b = _two_sub_builder()
        expected = b.build("test.Envelope", a=b.build("test.Sub", value=1))
        actual = b.build(
            "test.Envelope",
            a=b.build("test.Sub", value=1),
            b=b.build("test.Sub", value=5),
        )

        # Baseline (full): the actual-only sub-message 'b' reports as ADDED.
        full = MessageDifferencer().compare(expected, actual)
        added_full = {
            str(d.path) for d in full if d.change_type == ChangeType.ADDED
        }
        assert added_full == {"b.value"}

        # Partial: the whole actual-only subtree is suppressed -> equal.
        d = MessageDifferencer()
        d.set_partial()
        result = d.compare(expected, actual)
        assert not result.has_changes()

    def test_whole_expected_only_submessage_still_removed(self) -> None:
        """A whole expected-only sub-message is still REMOVED under partial (R5)."""
        b = _two_sub_builder()
        # 'b' set on expected, absent on actual -> expected-only subtree.
        expected = b.build(
            "test.Envelope",
            a=b.build("test.Sub", value=1),
            b=b.build("test.Sub", value=5),
        )
        actual = b.build("test.Envelope", a=b.build("test.Sub", value=1))

        # Baseline (full): the expected-only sub-message reports as REMOVED.
        full = MessageDifferencer().compare(expected, actual)
        removed_full = {
            str(d.path) for d in full if d.change_type == ChangeType.REMOVED
        }
        assert removed_full == {"b.value"}

        # Partial: REMOVED subtrees are directional and NOT suppressed.
        d = MessageDifferencer()
        d.set_partial()
        result = d.compare(expected, actual)
        removed = [r for r in result if r.change_type == ChangeType.REMOVED]
        assert {str(r.path) for r in removed} == {"b.value"}
        assert [r.left_value for r in removed] == [5]


# ---------------------------------------------------------------------------
# partial + treat_as_set carve-out (KTD-8): set elements stay strict
# ---------------------------------------------------------------------------


class TestPartialSetCarveOut:
    def test_partial_does_not_descend_into_scalar_set(self) -> None:
        """A scalar set element present only on actual is still reported.

        Partial relaxes field-shape, never set membership: under partial + set
        mode the extra actual element still surfaces as ADDED.
        """
        b = _set_scalar_builder()
        expected = b.build("test.Msg", tags=["x"])
        actual = b.build("test.Msg", tags=["x", "y"])

        # Baseline: set mode WITHOUT partial reports 'y' as the actual-only
        # leftover (ADDED).
        baseline = MessageDifferencer()
        baseline.treat_as_set("tags")
        base_result = baseline.compare(expected, actual)
        added_base = [a for a in base_result if a.change_type == ChangeType.ADDED]
        assert [a.right_value for a in added_base] == ["y"]

        # Mechanism: partial + set on the SAME field. Partial does not descend
        # into the set field -> 'y' is STILL reported (carve-out).
        d = MessageDifferencer()
        d.set_partial()
        d.treat_as_set("tags")
        result = d.compare(expected, actual)
        added = [a for a in result if a.change_type == ChangeType.ADDED]
        assert [a.right_value for a in added] == ["y"]

    def test_partial_does_not_descend_into_message_set(self) -> None:
        """A message set element present only on actual is still reported.

        The actual-only set *message* element is pushed as a force-emit work
        item, so partial's whole-subtree ADDED suppression does NOT drop it.
        """
        b = _set_elem_builder()
        expected = b.build(
            "test.Container",
            items=[b.build("test.Item", id="a", value=1)],
        )
        actual = b.build(
            "test.Container",
            items=[
                b.build("test.Item", id="a", value=1),
                b.build("test.Item", id="b", value=2),
            ],
        )

        # Baseline: set mode WITHOUT partial reports the unmatched actual
        # element 'b' as ADDED leaves.
        baseline = MessageDifferencer()
        baseline.treat_as_set("items")
        base_result = baseline.compare(expected, actual)
        added_base = {
            str(d.path) for d in base_result if d.change_type == ChangeType.ADDED
        }
        assert added_base != set()

        # Mechanism: partial + set. The strict set carve-out still reports the
        # actual-only message element (partial does not descend into set fields).
        d = MessageDifferencer()
        d.set_partial()
        d.treat_as_set("items")
        result = d.compare(expected, actual)
        added = {
            str(p.path) for p in result if p.change_type == ChangeType.ADDED
        }
        assert added == added_base
        assert added != set()

    def test_partial_set_strict_element_equality_reports_remove_add(self) -> None:
        """A near-equal set element pair reports remove+add even under partial.

        Set-element equality is strict (KTD-8), so a single differing sub-field
        is NOT relaxed by partial; it surfaces as expected-only REMOVED +
        actual-only ADDED rather than collapsing to nothing.
        """
        b = _set_elem_builder()
        expected = b.build(
            "test.Container",
            items=[b.build("test.Item", id="a", value=1)],
        )
        actual = b.build(
            "test.Container",
            items=[b.build("test.Item", id="a", value=99)],
        )

        d = MessageDifferencer()
        d.set_partial()
        d.treat_as_set("items")
        result = d.compare(expected, actual)
        # Strict pairing fails -> the expected element is REMOVED and the actual
        # element is ADDED (no collapse under partial).
        assert any(r.change_type == ChangeType.REMOVED for r in result)
        assert any(a.change_type == ChangeType.ADDED for a in result)


# ---------------------------------------------------------------------------
# partial over default (index-paired) repeated + map collections:
# extra elements/keys on actual are suppressed (actual ⊇ expected); a missing
# or differing expected element/key still reports. Regression guard for the
# "partial leaks extra repeated/map elements as ADDED" defect.
# ---------------------------------------------------------------------------


class TestPartialRepeatedExtras:
    def test_extra_repeated_element_on_actual_suppressed(self) -> None:
        """expected{tags=[x]}, actual{tags=[x,y]} (no set mode): partial passes."""
        b = _set_scalar_builder()
        expected = b.build("test.Msg", tags=["x"])
        actual = b.build("test.Msg", tags=["x", "y"])

        # Baseline: full mode reports the trailing actual-only element as ADDED.
        full = MessageDifferencer().compare(expected, actual)
        added_full = [a for a in full if a.change_type == ChangeType.ADDED]
        assert [a.right_value for a in added_full] == ["y"]

        # Mechanism: partial (index-paired, NOT set mode) suppresses the extra.
        d = MessageDifferencer()
        d.set_partial()
        result = d.compare(expected, actual)
        assert not result.has_changes()

    def test_missing_expected_repeated_element_still_removed(self) -> None:
        """An expected element absent on actual is still REMOVED under partial."""
        b = _set_scalar_builder()
        expected = b.build("test.Msg", tags=["x", "y"])
        actual = b.build("test.Msg", tags=["x"])

        d = MessageDifferencer()
        d.set_partial()
        result = d.compare(expected, actual)
        removed = [r for r in result if r.change_type == ChangeType.REMOVED]
        assert [r.left_value for r in removed] == ["y"]

    def test_differing_paired_repeated_element_still_modified(self) -> None:
        """A paired (index) element diff still reports; the extra is suppressed."""
        b = _set_scalar_builder()
        expected = b.build("test.Msg", tags=["x"])
        actual = b.build("test.Msg", tags=["z", "y"])

        d = MessageDifferencer()
        d.set_partial()
        result = d.compare(expected, actual)
        modified = [m for m in result if m.change_type == ChangeType.MODIFIED]
        assert [str(m.path) for m in modified] == ["tags[0]"]
        # index-1 actual-only element is suppressed.
        assert [a for a in result if a.change_type == ChangeType.ADDED] == []


class TestPartialMapExtras:
    def test_extra_map_key_on_actual_suppressed(self) -> None:
        """expected{labels={env}}, actual{labels={env,extra}}: partial passes."""
        b = _map_builder()
        expected = b.build("test.M", labels={"env": "prod"})
        actual = b.build("test.M", labels={"env": "prod", "extra": "leak"})

        # Baseline: full mode reports the actual-only key as ADDED.
        full = MessageDifferencer().compare(expected, actual)
        added_full = [a for a in full if a.change_type == ChangeType.ADDED]
        assert [a.right_value for a in added_full] == ["leak"]

        # Mechanism: partial suppresses the actual-only key.
        d = MessageDifferencer()
        d.set_partial()
        result = d.compare(expected, actual)
        assert not result.has_changes()

    def test_missing_expected_map_key_still_removed(self) -> None:
        """An expected key absent on actual is still REMOVED under partial."""
        b = _map_builder()
        expected = b.build("test.M", labels={"env": "prod", "team": "core"})
        actual = b.build("test.M", labels={"env": "prod"})

        d = MessageDifferencer()
        d.set_partial()
        result = d.compare(expected, actual)
        removed = [r for r in result if r.change_type == ChangeType.REMOVED]
        assert [r.left_value for r in removed] == ["core"]


class TestPartialTreatAsMapExtras:
    """``treat_as_map`` is a keyed collection like ``map<k,v>`` — not a set — so
    it takes the same actual-is-a-superset suppression, for empty and populated
    actual-only elements alike."""

    def test_extra_empty_keyed_element_on_actual_suppressed(self) -> None:
        b = _set_elem_builder()
        expected = b.build(
            "test.Container", items=[b.build("test.Item", id="a", value=1)],
        )
        actual = b.build(
            "test.Container",
            items=[b.build("test.Item", id="a", value=1), b.build("test.Item")],
        )

        # Baseline: full mode reports the empty actual-only element as ADDED.
        full = MessageDifferencer()
        full.treat_as_map("items", key="id")
        added_full = [a for a in full.compare(expected, actual)
                      if a.change_type == ChangeType.ADDED]
        assert [str(a.path) for a in added_full] == ['items[id=""]']

        # Mechanism: partial suppresses it.
        d = MessageDifferencer()
        d.treat_as_map("items", key="id")
        d.set_partial()
        assert not d.compare(expected, actual).has_changes()

    def test_extra_populated_keyed_element_on_actual_suppressed(self) -> None:
        b = _set_elem_builder()
        expected = b.build(
            "test.Container", items=[b.build("test.Item", id="a", value=1)],
        )
        actual = b.build(
            "test.Container",
            items=[
                b.build("test.Item", id="a", value=1),
                b.build("test.Item", id="z", value=9),
            ],
        )

        full = MessageDifferencer()
        full.treat_as_map("items", key="id")
        added_full = [a for a in full.compare(expected, actual)
                      if a.change_type == ChangeType.ADDED]
        assert [str(a.path) for a in added_full] == ['items[id="z"].id',
                                                     'items[id="z"].value']

        d = MessageDifferencer()
        d.treat_as_map("items", key="id")
        d.set_partial()
        assert not d.compare(expected, actual).has_changes()

    def test_missing_expected_keyed_element_still_removed(self) -> None:
        """An expected key absent on actual is still REMOVED under partial."""
        b = _set_elem_builder()
        expected = b.build(
            "test.Container",
            items=[
                b.build("test.Item", id="a", value=1),
                b.build("test.Item", id="b", value=2),
            ],
        )
        actual = b.build(
            "test.Container", items=[b.build("test.Item", id="a", value=1)],
        )

        d = MessageDifferencer()
        d.treat_as_map("items", key="id")
        d.set_partial()
        removed = [r for r in d.compare(expected, actual)
                   if r.change_type == ChangeType.REMOVED]
        assert [str(r.path) for r in removed] == ['items[id="b"].id',
                                                  'items[id="b"].value']


class TestPartialPresenceBranch:
    """Exercise the ``has_presence`` branch of ``_present_on_expected`` under
    partial via a proto3 ``optional`` field (explicit presence)."""

    def test_optional_set_on_expected_is_compared_under_partial(self) -> None:
        """flag set (even to default) on expected → HasField True → in sub-shape."""
        b = _opt_builder()
        cls = b.get_message_class("test.Opt")
        expected = cls(flag=0)  # explicitly set to default → HasField True
        actual = cls(flag=5)

        d = MessageDifferencer()
        d.set_partial()
        result = d.compare(expected, actual)
        assert {
            str(m.path) for m in result if m.change_type == ChangeType.MODIFIED
        } == {"flag"}

    def test_optional_unset_on_expected_is_outside_subshape(self) -> None:
        """flag unset on expected → HasField False → outside the sub-shape."""
        b = _opt_builder()
        cls = b.get_message_class("test.Opt")
        expected = cls()  # flag unset → HasField False
        actual = cls(flag=5)

        # Baseline: full mode reports the set-on-actual-only optional field.
        full = MessageDifferencer().compare(expected, actual)
        assert full.has_changes()

        # Partial: the has_presence branch returns False → field suppressed.
        d = MessageDifferencer()
        d.set_partial()
        result = d.compare(expected, actual)
        assert not result.has_changes()


# ---------------------------------------------------------------------------
# Default (full) mode regression: partial off changes nothing
# ---------------------------------------------------------------------------


class TestFullModeUnchanged:
    def test_full_mode_reports_extra_actual_scalars(self) -> None:
        """With partial off (default), extras on actual still report (R12).

        proto3 implicit scalars surface as MODIFIED (default->value), not ADDED.
        """
        b = _user_builder()
        expected = b.build("test.User", name="Alice")
        actual = b.build("test.User", name="Alice", email="a@x.com", id=7)

        d = MessageDifferencer()  # default: partial off
        result = d.compare(expected, actual)
        modified = {str(p.path) for p in result if p.change_type == ChangeType.MODIFIED}
        assert modified == {"email", "id"}

    def test_full_mode_explicit_off_matches_default(self) -> None:
        """set_partial(False) restores full comparison."""
        b = _nested_builder()
        expected = b.build(
            "test.Envelope", header=b.build("test.Header", version=2),
        )
        actual = b.build(
            "test.Envelope",
            header=b.build("test.Header", version=2, note="hello"),
        )

        default_result = MessageDifferencer().compare(expected, actual)

        d = MessageDifferencer()
        d.set_partial(True)
        d.set_partial(False)
        toggled = d.compare(expected, actual)

        assert {str(x.path) for x in toggled} == {
            str(x.path) for x in default_result
        }
        assert toggled.has_changes()
