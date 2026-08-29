"""Tests for the framework-agnostic proto matcher (U7, R1/R2/R12/R13).

Covers the public matcher surface in ``protokit.message.matchers``:

* :func:`proto_match` (single-call) and :func:`expect_proto` (fluent) raise a
  plain :class:`AssertionError` carrying the engine's per-field rich diff on
  mismatch, and do not raise on match.
* The single-call and fluent forms produce identical pass/fail AND identical
  message text for the same policy (R2).
* Each policy knob (partial, as_set, ignore-predicate, presence, approx) wires
  through to its engine unit. These do NOT re-test the engine deeply — U2–U6
  already pin the behavior — they prove the matcher WIRES each knob.
* :class:`MatchPolicy` is frozen: a mutated input list does not change the
  policy (snapshot), and a contradictory paired-field config raises at
  construction.
* Directionality: ``proto_match(actual, expected)`` maps expected->left, so
  partial ignores actual-only extras (KTD-5).
* Strict-warnings guard: a matcher comparison under
  ``simplefilter("error", UserWarning)`` does not raise — proving no deprecated
  ``old_value`` / ``new_value`` alias reads (KTD-4).
"""

from __future__ import annotations

import dataclasses
import warnings
from typing import Any

import pytest
from google.protobuf import descriptor_pb2

from protokit.message import (
    Approx,
    MatcherError,
    MatchPolicy,
    MessageFieldComparison,
    expect_proto,
    proto_match,
)
from tests.proto_builder import ProtoBuilder

T = descriptor_pb2.FieldDescriptorProto


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _user_builder() -> ProtoBuilder:
    """Flat ``User{name, email, id}`` (all singular scalars)."""
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


def _tags_builder() -> ProtoBuilder:
    """``Doc{tags: repeated string}`` for set-comparison wiring."""
    b = ProtoBuilder()
    b.message_with_repeated(
        "test.Doc",
        {"tags": (T.TYPE_STRING, 1)},
        repeated_fields={"tags"},
    )
    return b


def _internal_builder() -> ProtoBuilder:
    """``Rec{value, debug_internal}`` for predicate-ignore wiring."""
    b = ProtoBuilder()
    b.message(
        "test.Rec",
        {
            "value": (T.TYPE_STRING, 1),
            "debug_internal": (T.TYPE_STRING, 2),
        },
    )
    return b


def _opt_builder() -> ProtoBuilder:
    """``Opt{flag: optional int32}`` (proto3 explicit presence) for presence wiring."""
    b = ProtoBuilder()
    b.message(
        "test.Opt",
        {"flag": (T.TYPE_INT32, 1)},
        optional_fields={"flag"},
    )
    return b


def _ratio_builder() -> ProtoBuilder:
    """``Msg{ratio: double, other: double}`` for approx wiring."""
    b = ProtoBuilder()
    b.message(
        "test.Msg",
        {
            "ratio": (T.TYPE_DOUBLE, 1),
            "other": (T.TYPE_DOUBLE, 2),
        },
    )
    return b


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestHappyPath:
    """Equal messages pass; differing messages raise a rich AssertionError."""

    def test_equal_messages_do_not_raise(self) -> None:
        b = _user_builder()
        cls = b.get_message_class("test.User")
        expected = cls(name="Alice", email="a@x", id=1)
        actual = cls(name="Alice", email="a@x", id=1)
        proto_match(actual, expected)  # no raise

    def test_differing_messages_raise_with_per_field_diff(self) -> None:
        b = _user_builder()
        cls = b.get_message_class("test.User")
        expected = cls(name="Alice", email="a@x", id=1)
        actual = cls(name="Bob", email="a@x", id=1)
        with pytest.raises(AssertionError) as exc:
            proto_match(actual, expected)
        msg = str(exc.value)
        # The per-field diff names the differing field and both values.
        assert "name" in msg
        assert "Alice" in msg
        assert "Bob" in msg

    def test_fluent_equal_does_not_raise(self) -> None:
        b = _user_builder()
        cls = b.get_message_class("test.User")
        expected = cls(name="Alice", email="a@x", id=1)
        actual = cls(name="Alice", email="a@x", id=1)
        expect_proto(expected).matches(actual)  # no raise

    def test_fluent_assert_matches_alias(self) -> None:
        b = _user_builder()
        cls = b.get_message_class("test.User")
        expected = cls(name="Alice")
        actual = cls(name="Bob")
        with pytest.raises(AssertionError):
            expect_proto(expected).assert_matches(actual)


# ---------------------------------------------------------------------------
# Single-call vs fluent parity (R2)
# ---------------------------------------------------------------------------


class TestSingleCallFluentParity:
    """Both forms produce identical pass/fail AND identical message text."""

    def test_identical_pass(self) -> None:
        b = _user_builder()
        cls = b.get_message_class("test.User")
        expected = cls(name="Alice", id=1)
        actual = cls(name="Alice", id=1)
        # Both pass; neither raises.
        proto_match(actual, expected)
        expect_proto(expected).matches(actual)

    def test_identical_fail_message(self) -> None:
        b = _user_builder()
        cls = b.get_message_class("test.User")
        expected = cls(name="Alice", email="a@x", id=1)
        actual = cls(name="Bob", email="b@y", id=2)

        with pytest.raises(AssertionError) as single_exc:
            proto_match(actual, expected)
        with pytest.raises(AssertionError) as fluent_exc:
            expect_proto(expected).matches(actual)

        assert str(single_exc.value) == str(fluent_exc.value)

    def test_identical_fail_message_with_policy_knob(self) -> None:
        # Same policy (partial) through both surfaces -> identical text.
        b = _user_builder()
        cls = b.get_message_class("test.User")
        expected = cls(name="Alice", email="MISMATCH")
        actual = cls(name="Alice", email="other", id=7)

        with pytest.raises(AssertionError) as single_exc:
            proto_match(actual, expected, partial=True)
        with pytest.raises(AssertionError) as fluent_exc:
            expect_proto(expected).partially().matches(actual)

        assert str(single_exc.value) == str(fluent_exc.value)


# ---------------------------------------------------------------------------
# Per-knob wiring (one focused test each)
# ---------------------------------------------------------------------------


class TestPartialWiring:
    """partial=True ignores fields present only on actual (KTD-5 directionality)."""

    def test_partial_ignores_actual_only_extras(self) -> None:
        b = _user_builder()
        cls = b.get_message_class("test.User")
        expected = cls(name="Alice")
        actual = cls(name="Alice", email="extra@x", id=99)

        # Baseline: full comparison reports the actual-only extras.
        with pytest.raises(AssertionError):
            proto_match(actual, expected)

        # Partial: extras on actual are not differences.
        proto_match(actual, expected, partial=True)
        expect_proto(expected).partially().matches(actual)

    def test_partial_still_reports_differing_expected_field(self) -> None:
        b = _user_builder()
        cls = b.get_message_class("test.User")
        expected = cls(name="Alice")
        actual = cls(name="Bob", email="extra@x")
        with pytest.raises(AssertionError):
            proto_match(actual, expected, partial=True)


class TestAsSetWiring:
    """as_set compares a repeated field order-independently (U3)."""

    def test_unordered_repeated_passes_under_set(self) -> None:
        b = _tags_builder()
        cls = b.get_message_class("test.Doc")
        expected = cls(tags=["x", "y"])
        actual = cls(tags=["y", "x"])

        # Baseline: index-pairing reports the reordering.
        with pytest.raises(AssertionError):
            proto_match(actual, expected)

        # Set mode: order-independent.
        proto_match(actual, expected, as_set="tags")
        expect_proto(expected).as_set("tags").matches(actual)

    def test_set_reports_unmatched_elements(self) -> None:
        b = _tags_builder()
        cls = b.get_message_class("test.Doc")
        expected = cls(tags=["x", "z"])
        actual = cls(tags=["y", "x"])
        with pytest.raises(AssertionError) as exc:
            proto_match(actual, expected, as_set="tags")
        msg = str(exc.value)
        assert "z" in msg  # expected-side leftover
        assert "y" in msg  # actual-side leftover


class TestIgnoreWiring:
    """ignore accepts a predicate over (FieldDescriptor, FieldPath) (U2)."""

    def test_predicate_ignore_suppresses_matching_field(self) -> None:
        b = _internal_builder()
        cls = b.get_message_class("test.Rec")
        expected = cls(value="same", debug_internal="A")
        actual = cls(value="same", debug_internal="B")

        # Baseline: the *_internal difference is real.
        with pytest.raises(AssertionError):
            proto_match(actual, expected)

        def ignore_internal(fd: Any, path: Any) -> bool:
            return bool(fd.name.endswith("_internal"))

        proto_match(actual, expected, ignore=ignore_internal)
        expect_proto(expected).ignoring(ignore_internal).matches(actual)

    def test_string_path_ignore(self) -> None:
        b = _internal_builder()
        cls = b.get_message_class("test.Rec")
        expected = cls(value="same", debug_internal="A")
        actual = cls(value="same", debug_internal="B")
        proto_match(actual, expected, ignore="debug_internal")


class TestPresenceWiring:
    """presence=EQUAL distinguishes set-to-default from unset (U5)."""

    def test_equal_distinguishes_default_from_unset(self) -> None:
        b = _opt_builder()
        cls = b.get_message_class("test.Opt")
        expected = cls()  # flag unset
        actual = cls(flag=0)  # flag set to its default

        # EQUIVALENT (default): set-to-default collapses to unset -> equal.
        proto_match(actual, expected)
        proto_match(actual, expected, presence=MessageFieldComparison.EQUIVALENT)

        # EQUAL: a present-but-default field vs unset is a presence difference.
        with pytest.raises(AssertionError):
            proto_match(actual, expected, presence=MessageFieldComparison.EQUAL)
        with pytest.raises(AssertionError):
            expect_proto(expected).strict_presence().matches(actual)

    def test_with_presence_equal_method(self) -> None:
        b = _opt_builder()
        cls = b.get_message_class("test.Opt")
        expected = cls()
        actual = cls(flag=0)
        with pytest.raises(AssertionError):
            expect_proto(expected).with_presence(
                MessageFieldComparison.EQUAL
            ).matches(actual)


class TestApproxWiring:
    """approx applies float tolerance, globally or per-field (U6)."""

    def test_global_margin_suppresses_subtolerance_diff(self) -> None:
        b = _ratio_builder()
        cls = b.get_message_class("test.Msg")
        expected = cls(ratio=0.1, other=1.0)
        actual = cls(ratio=0.1000001, other=1.0)

        # Baseline: exact comparison reports the sub-tolerance difference.
        with pytest.raises(AssertionError):
            proto_match(actual, expected)

        # Global margin via the flat shorthand.
        proto_match(actual, expected, margin=1e-5)
        # And via the Approx helper.
        proto_match(actual, expected, approx=Approx(margin=1e-5))
        # And fluently.
        expect_proto(expected).approximately(margin=1e-5).matches(actual)

    def test_per_field_overlay_via_fluent(self) -> None:
        b = _ratio_builder()
        cls = b.get_message_class("test.Msg")
        expected = cls(ratio=0.1, other=1.0)
        actual = cls(ratio=0.1000001, other=1.0000001)

        # Overlay scoped to ratio only: ratio is loosened, other still exact.
        with pytest.raises(AssertionError) as exc:
            expect_proto(expected).approximately(
                margin=1e-5, selector="ratio"
            ).matches(actual)
        msg = str(exc.value)
        assert "other" in msg
        assert "ratio" not in msg

    def test_global_fraction_shorthand_suppresses_relative_diff(self) -> None:
        """The ``fraction=`` relative-tolerance shorthand wires through (U6).

        Distinct from ``margin=`` (absolute): proves the ``fraction`` branch of
        ``_approx_from_kwargs`` -> ``Approx.from_optional`` reaches the engine.
        """
        b = _ratio_builder()
        cls = b.get_message_class("test.Msg")
        expected = cls(ratio=1000.0, other=1.0)
        actual = cls(ratio=1000.05, other=1.0)  # ~5e-5 relative

        # Baseline: exact comparison reports the difference.
        with pytest.raises(AssertionError):
            proto_match(actual, expected)

        # Relative shorthand admits it (5e-5 < 1e-4) ...
        proto_match(actual, expected, fraction=1e-4)
        # ... and the explicit Approx(fraction=...) form is equivalent.
        proto_match(actual, expected, approx=Approx(fraction=1e-4))


# ---------------------------------------------------------------------------
# Cross-schema failure header
# ---------------------------------------------------------------------------


class TestCrossSchemaHeader:
    """When expected and actual are different message types, the failure header
    names both types and flags the comparison as cross-schema."""

    def test_cross_schema_mismatch_header_names_both_types(self) -> None:
        b = ProtoBuilder()
        b.message("test.Alpha", {"x": (T.TYPE_INT32, 1)})
        b.message("test.Beta", {"x": (T.TYPE_INT32, 1)})
        expected = b.build("test.Alpha", x=1)
        actual = b.build("test.Beta", x=2)

        with pytest.raises(AssertionError) as exc:
            proto_match(actual, expected)
        msg = str(exc.value)
        assert "cross-schema" in msg
        assert "test.Alpha" in msg
        assert "test.Beta" in msg


# ---------------------------------------------------------------------------
# MatchPolicy frozen semantics
# ---------------------------------------------------------------------------


class TestMatchPolicyFrozen:
    """Snapshot of mutable inputs + paired-field invariant at construction."""

    def test_mutating_input_list_after_construction_does_not_change_policy(self) -> None:
        ignore_list = ["a", "b"]
        policy = MatchPolicy(ignore=ignore_list)
        ignore_list.append("c")
        # The policy snapshotted to a tuple; the later append is not reflected.
        assert policy.ignore == ("a", "b")
        assert isinstance(policy.ignore, tuple)

    def test_as_set_and_overlays_snapshotted(self) -> None:
        as_set_list = ["tags"]
        overlay_list = [("ratio", Approx(margin=1e-5))]
        policy = MatchPolicy(as_set=as_set_list, approx_overlays=overlay_list)
        as_set_list.append("more")
        overlay_list.append(("other", Approx()))
        assert policy.as_set == ("tags",)
        assert policy.approx_overlays == (("ratio", Approx(margin=1e-5)),)

    def test_bare_string_selector_is_one_selector_not_per_character(self) -> None:
        """A bare ``str`` is a single dotted path, not an iterable of chars.

        ``__post_init__`` snapshots collection inputs with ``tuple(...)``,
        and ``str`` is iterable — so a bare name silently exploded into
        one selector per character. ``MatchPolicy(ignore="name")`` became
        ``("n", "a", "m", "e")``: four selectors that match nothing, so the
        field the caller asked to ignore was compared anyway and the
        mistake was invisible (no error, just a stricter comparison than
        requested). ``proto_match``'s own ``_as_tuple`` coercion always
        handled this; the dataclass bypassed it.
        """
        assert MatchPolicy(ignore="name").ignore == ("name",)
        assert MatchPolicy(as_set="items").as_set == ("items",)
        assert MatchPolicy(ignore="outer.inner.leaf").ignore == ("outer.inner.leaf",)
        # An iterable of names still snapshots element-wise.
        assert MatchPolicy(ignore=["a", "b"]).ignore == ("a", "b")

    def test_contradictory_presence_raises_at_construction(self) -> None:
        with pytest.raises(MatcherError, match="presence must be a MessageFieldComparison"):
            MatchPolicy(presence="EQUAL")  # type: ignore[arg-type]

    def test_policy_is_frozen(self) -> None:
        policy = MatchPolicy()
        with pytest.raises(dataclasses.FrozenInstanceError):
            policy.partial = True  # type: ignore[misc]

    def test_contradictory_approx_kwargs_raise(self) -> None:
        b = _ratio_builder()
        cls = b.get_message_class("test.Msg")
        m = cls(ratio=0.1)
        with pytest.raises(MatcherError, match="not both"):
            proto_match(m, m, approx=Approx(margin=1e-5), margin=1e-5)


# ---------------------------------------------------------------------------
# Directionality (KTD-5): expected -> left
# ---------------------------------------------------------------------------


class TestDirectionality:
    """proto_match(actual, expected) maps expected to the differ's left side."""

    def test_partial_with_extra_on_actual_passes(self) -> None:
        b = _user_builder()
        cls = b.get_message_class("test.User")
        expected = cls(name="Alice")
        # actual carries fields expected does not — proves expected==left, so
        # partial suppresses the actual-only (right-only) ADDED differences.
        actual = cls(name="Alice", email="x@y", id=42)
        proto_match(actual, expected, partial=True)

    def test_partial_with_missing_on_actual_fails(self) -> None:
        # Reverse: expected has a field actual lacks -> still reported (REMOVED).
        b = _user_builder()
        cls = b.get_message_class("test.User")
        expected = cls(name="Alice", email="x@y")
        actual = cls(name="Alice")
        with pytest.raises(AssertionError):
            proto_match(actual, expected, partial=True)


# ---------------------------------------------------------------------------
# Predicate exceptions propagate (KTD-10 / SWI-3)
# ---------------------------------------------------------------------------


class TestPredicateExceptionsPropagate:
    """A raising ignore/selector predicate surfaces the author's exception."""

    def test_raising_ignore_predicate_propagates(self) -> None:
        b = _internal_builder()
        cls = b.get_message_class("test.Rec")
        expected = cls(value="a")
        actual = cls(value="b")

        class BoomError(Exception):
            pass

        def boom(fd: object, path: object) -> bool:
            raise BoomError("author bug")

        with pytest.raises(BoomError, match="author bug"):
            proto_match(actual, expected, ignore=boom)


# ---------------------------------------------------------------------------
# Strict-warnings guard (KTD-4)
# ---------------------------------------------------------------------------


class TestStrictWarningsGuard:
    """A matcher comparison reads only canonical left/right — no alias warnings."""

    def test_matcher_run_is_warning_clean(self) -> None:
        b = _user_builder()
        cls = b.get_message_class("test.User")
        expected = cls(name="Alice", email="a@x", id=1)
        actual = cls(name="Bob", email="b@y", id=2)

        with warnings.catch_warnings():
            warnings.simplefilter("error", UserWarning)
            # Mismatch path renders the diff; must not touch old_value/new_value.
            with pytest.raises(AssertionError):
                proto_match(actual, expected)
            # And the equal path is likewise clean.
            proto_match(expected, expected)
