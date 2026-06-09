"""Tests for the optional PyHamcrest adapter (U8, R3, AE7).

Covers ``protokit.message.hamcrest.equals_proto`` — the ``hamcrest.BaseMatcher``
front-end over the same policy → differ → diff path as the agnostic matcher:

* ``assert_that(actual, equals_proto(expected).partially())`` passes/fails
  IDENTICALLY to ``proto_match(actual, expected, partial=True)`` (AE7).
* ``describe_mismatch`` surfaces the per-field rich diff (via the shared
  formatter, not an independent one).
* SURFACE-PARITY (SWI-1): the same ``MatchPolicy`` driven through the agnostic
  matcher and through the adapter yields identical pass/fail AND identical
  rendered diff text.
* Directionality, every fluent knob, and predicate-exception propagation match
  the agnostic surface.

Collection is gated with ``pytest.importorskip("hamcrest")`` at MODULE TOP — a
module-level guard is required because the imports below run at collection time
(``pytestmark`` does NOT guard module-top imports; see
``docs/solutions/test-failures/pytestmark-does-not-guard-module-top-imports-2026-05-02.md``).
On an env without the ``[hamcrest]`` extra this module is skipped wholesale; the
extra-ABSENT guard path is covered separately by ``test_hamcrest_extra.py``
(which does NOT importorskip).
"""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("hamcrest")

from hamcrest import assert_that  # noqa: E402 — after the importorskip guard

from protokit.message import MessageFieldComparison  # noqa: E402
from protokit.message.hamcrest import equals_proto  # noqa: E402
from protokit.message.matchers import (  # noqa: E402
    Approx,
    MatchPolicy,
    _build_differ,
    expect_proto,
    proto_match,
)
from protokit.message.pytest_plugin import render_diff_lines  # noqa: E402
from tests.proto_builder import ProtoBuilder  # noqa: E402

from google.protobuf import descriptor_pb2  # noqa: E402  # isort: skip

T = descriptor_pb2.FieldDescriptorProto


# ---------------------------------------------------------------------------
# Builders (mirror tests/test_proto_match.py so parity is apples-to-apples)
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
    """``Opt{flag: optional int32}`` (proto3 explicit presence)."""
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
# equals_proto returns a real hamcrest BaseMatcher
# ---------------------------------------------------------------------------


class TestReturnsBaseMatcher:
    """The factory returns a usable ``hamcrest.BaseMatcher`` (lazy subclass)."""

    def test_is_a_base_matcher_instance(self) -> None:
        from hamcrest.core.base_matcher import BaseMatcher

        b = _user_builder()
        cls = b.get_message_class("test.User")
        matcher = equals_proto(cls(name="Alice"))
        assert isinstance(matcher, BaseMatcher)

    def test_equal_messages_pass_with_assert_that(self) -> None:
        b = _user_builder()
        cls = b.get_message_class("test.User")
        expected = cls(name="Alice", email="a@x", id=1)
        actual = cls(name="Alice", email="a@x", id=1)
        assert_that(actual, equals_proto(expected))  # no raise

    def test_differing_messages_fail_with_assert_that(self) -> None:
        b = _user_builder()
        cls = b.get_message_class("test.User")
        expected = cls(name="Alice")
        actual = cls(name="Bob")
        with pytest.raises(AssertionError):
            assert_that(actual, equals_proto(expected))


# ---------------------------------------------------------------------------
# AE7: adapter pass/fail equivalent to the agnostic matcher
# ---------------------------------------------------------------------------


class TestAE7Equivalence:
    """``equals_proto(...).partially()`` matches ``proto_match(partial=True)``."""

    def test_partial_passes_identically(self) -> None:
        b = _user_builder()
        cls = b.get_message_class("test.User")
        expected = cls(name="Alice")
        actual = cls(name="Alice", email="extra@x", id=99)

        # Agnostic: partial passes (actual-only extras suppressed).
        proto_match(actual, expected, partial=True)
        # Adapter: same.
        assert_that(actual, equals_proto(expected).partially())

    def test_partial_fails_identically(self) -> None:
        b = _user_builder()
        cls = b.get_message_class("test.User")
        expected = cls(name="Alice")
        actual = cls(name="Bob", email="extra@x")

        # Both surfaces fail: a differing expected-present field fails partial.
        with pytest.raises(AssertionError):
            proto_match(actual, expected, partial=True)
        with pytest.raises(AssertionError):
            assert_that(actual, equals_proto(expected).partially())

    def test_full_mode_extra_on_actual_fails_both(self) -> None:
        b = _user_builder()
        cls = b.get_message_class("test.User")
        expected = cls(name="Alice")
        actual = cls(name="Alice", email="extra@x")

        with pytest.raises(AssertionError):
            proto_match(actual, expected)  # full mode reports the extra
        with pytest.raises(AssertionError):
            assert_that(actual, equals_proto(expected))  # adapter agrees


# ---------------------------------------------------------------------------
# describe_mismatch surfaces the per-field diff (via the shared formatter)
# ---------------------------------------------------------------------------


class TestDescribeMismatch:
    """The mismatch description carries the engine's per-field rich diff."""

    def test_mismatch_message_contains_per_field_diff(self) -> None:
        b = _user_builder()
        cls = b.get_message_class("test.User")
        expected = cls(name="Alice")
        actual = cls(name="Bob")
        with pytest.raises(AssertionError) as exc:
            assert_that(actual, equals_proto(expected))
        msg = str(exc.value)
        assert "name" in msg
        assert "Alice" in msg
        assert "Bob" in msg

    def test_describe_mismatch_matches_shared_formatter_text(self) -> None:
        # The diff text the adapter appends is exactly render_diff_lines output.
        from hamcrest.core.string_description import StringDescription

        b = _user_builder()
        cls = b.get_message_class("test.User")
        expected = cls(name="Alice", email="a@x")
        actual = cls(name="Bob", email="b@y")

        matcher = equals_proto(expected)
        desc = StringDescription()
        matcher.matches(actual, desc)  # populates desc on mismatch

        # Independently render via the shared formatter on the same policy.
        differ = _build_differ(MatchPolicy())
        result = differ.compare(expected, actual)
        header = f"proto match failed: expected != actual ({expected.DESCRIPTOR.full_name})"
        expected_text = "\n".join(render_diff_lines(result, header))

        assert expected_text in str(desc)


# ---------------------------------------------------------------------------
# SURFACE-PARITY (SWI-1): same policy -> identical pass/fail AND diff text
# ---------------------------------------------------------------------------


def _agnostic_outcome(policy: MatchPolicy, actual: Any, expected: Any) -> tuple[bool, str]:
    """Run the policy through the agnostic ``_assert_matches`` path.

    Returns ``(passed, message)`` — ``message`` is the empty string on pass.
    """
    from protokit.message.matchers import _assert_matches

    try:
        _assert_matches(policy, actual, expected)
        return True, ""
    except AssertionError as exc:
        return False, str(exc)


def _adapter_outcome(policy: MatchPolicy, actual: Any, expected: Any) -> tuple[bool, str]:
    """Run the SAME policy through the adapter's BaseMatcher path.

    Builds the matcher directly from the policy (bypassing the fluent builder)
    so the two surfaces are driven from one identical ``MatchPolicy`` object.
    """
    from hamcrest.core.string_description import StringDescription

    from protokit.message.hamcrest import _proto_matcher_class

    matcher = _proto_matcher_class()(expected, policy)
    desc = StringDescription()
    passed = matcher.matches(actual, desc)
    return passed, str(desc)


class TestSurfaceParity:
    """One MatchPolicy through both surfaces -> identical pass/fail + diff text."""

    def test_parity_equal_messages(self) -> None:
        b = _user_builder()
        cls = b.get_message_class("test.User")
        expected = cls(name="Alice", id=1)
        actual = cls(name="Alice", id=1)
        policy = MatchPolicy()

        a_pass, _ = _agnostic_outcome(policy, actual, expected)
        h_pass, _ = _adapter_outcome(policy, actual, expected)
        assert a_pass is True
        assert h_pass is True

    def test_parity_failing_messages_identical_diff_text(self) -> None:
        b = _user_builder()
        cls = b.get_message_class("test.User")
        expected = cls(name="Alice", email="a@x", id=1)
        actual = cls(name="Bob", email="b@y", id=2)
        policy = MatchPolicy()

        a_pass, a_msg = _agnostic_outcome(policy, actual, expected)
        h_pass, h_msg = _adapter_outcome(policy, actual, expected)

        assert a_pass is False
        assert h_pass is False
        # Identical rendered diff text (the agnostic AssertionError message is
        # exactly the lines the adapter appends to its mismatch description).
        assert a_msg == h_msg

    def test_parity_under_partial_policy(self) -> None:
        b = _user_builder()
        cls = b.get_message_class("test.User")
        expected = cls(name="Alice", email="MISMATCH")
        actual = cls(name="Alice", email="other", id=7)
        policy = MatchPolicy(partial=True)

        a_pass, a_msg = _agnostic_outcome(policy, actual, expected)
        h_pass, h_msg = _adapter_outcome(policy, actual, expected)

        assert a_pass == h_pass
        assert a_pass is False  # the email field differs under partial
        assert a_msg == h_msg

    def test_parity_under_as_set_policy(self) -> None:
        b = _tags_builder()
        cls = b.get_message_class("test.Doc")
        expected = cls(tags=["x", "z"])
        actual = cls(tags=["y", "x"])
        policy = MatchPolicy(as_set=("tags",))

        a_pass, a_msg = _agnostic_outcome(policy, actual, expected)
        h_pass, h_msg = _adapter_outcome(policy, actual, expected)

        assert a_pass == h_pass
        assert a_pass is False
        assert a_msg == h_msg

    def test_parity_under_presence_policy(self) -> None:
        b = _opt_builder()
        cls = b.get_message_class("test.Opt")
        # flag set-to-default on expected vs unset on actual: EQUAL reports the
        # presence delta (EQUIVALENT would collapse it).
        expected = cls(flag=0)
        actual = cls()
        policy = MatchPolicy(presence=MessageFieldComparison.EQUAL)

        a_pass, a_msg = _agnostic_outcome(policy, actual, expected)
        h_pass, h_msg = _adapter_outcome(policy, actual, expected)

        assert a_pass == h_pass
        assert a_pass is False
        assert a_msg == h_msg

    def test_parity_under_approx_policy(self) -> None:
        b = _ratio_builder()
        cls = b.get_message_class("test.Msg")
        # ratio differs within tolerance (suppressed); other differs beyond it.
        expected = cls(ratio=0.1, other=1.0)
        actual = cls(ratio=0.1000001, other=2.0)
        policy = MatchPolicy(approx=Approx(margin=1e-5))

        a_pass, a_msg = _agnostic_outcome(policy, actual, expected)
        h_pass, h_msg = _adapter_outcome(policy, actual, expected)

        assert a_pass == h_pass
        assert a_pass is False
        # approx is genuinely active: ratio is within tolerance, only other fails.
        assert "ratio" not in a_msg
        assert "other" in a_msg
        assert a_msg == h_msg


# ---------------------------------------------------------------------------
# Fluent-knob wiring: each adapter chain matches its expect_proto sibling
# ---------------------------------------------------------------------------


class TestFluentKnobParity:
    """Each adapter fluent method mirrors the expect_proto chain (one each)."""

    def test_ignoring_predicate(self) -> None:
        b = _internal_builder()
        cls = b.get_message_class("test.Rec")
        expected = cls(value="same", debug_internal="A")
        actual = cls(value="same", debug_internal="B")

        def ignore_internal(fd: Any, path: Any) -> bool:
            return bool(fd.name.endswith("_internal"))

        # Baseline: the *_internal difference is real on both surfaces.
        with pytest.raises(AssertionError):
            assert_that(actual, equals_proto(expected))

        expect_proto(expected).ignoring(ignore_internal).matches(actual)
        assert_that(actual, equals_proto(expected).ignoring(ignore_internal))

    def test_as_set(self) -> None:
        b = _tags_builder()
        cls = b.get_message_class("test.Doc")
        expected = cls(tags=["x", "y"])
        actual = cls(tags=["y", "x"])

        with pytest.raises(AssertionError):
            assert_that(actual, equals_proto(expected))  # index-pairing fails

        assert_that(actual, equals_proto(expected).as_set("tags"))

    def test_strict_presence(self) -> None:
        b = _opt_builder()
        cls = b.get_message_class("test.Opt")
        expected = cls()  # flag unset
        actual = cls(flag=0)  # set to its default

        # EQUIVALENT default: collapses -> passes.
        assert_that(actual, equals_proto(expected))
        # EQUAL: distinguishes default-from-unset -> fails.
        with pytest.raises(AssertionError):
            assert_that(actual, equals_proto(expected).strict_presence())
        with pytest.raises(AssertionError):
            assert_that(
                actual,
                equals_proto(expected).with_presence(MessageFieldComparison.EQUAL),
            )

    def test_approximately_global(self) -> None:
        b = _ratio_builder()
        cls = b.get_message_class("test.Msg")
        expected = cls(ratio=0.1, other=1.0)
        actual = cls(ratio=0.1000001, other=1.0)

        with pytest.raises(AssertionError):
            assert_that(actual, equals_proto(expected))  # sub-tolerance diff

        assert_that(actual, equals_proto(expected).approximately(margin=1e-5))

    def test_approximately_per_field_overlay(self) -> None:
        b = _ratio_builder()
        cls = b.get_message_class("test.Msg")
        expected = cls(ratio=0.1, other=1.0)
        actual = cls(ratio=0.1000001, other=1.0000001)

        # Overlay scoped to ratio only: ratio loosened, other still exact -> fail.
        with pytest.raises(AssertionError) as exc:
            assert_that(
                actual,
                equals_proto(expected).approximately(margin=1e-5, selector="ratio"),
            )
        msg = str(exc.value)
        assert "other" in msg

    def test_approx_helper_equivalence(self) -> None:
        # Approx is re-exported usage; the fluent margin path builds the same.
        b = _ratio_builder()
        cls = b.get_message_class("test.Msg")
        expected = cls(ratio=0.1)
        actual = cls(ratio=0.1000001)
        # margin loosens both surfaces.
        assert Approx(margin=1e-5).margin == 1e-5
        assert_that(actual, equals_proto(expected).approximately(margin=1e-5))


# ---------------------------------------------------------------------------
# Immutable fluent builder (each step returns a fresh matcher)
# ---------------------------------------------------------------------------


class TestFluentImmutability:
    """Fluent steps return new matchers; a base matcher is not mutated."""

    def test_partially_returns_new_matcher(self) -> None:
        b = _user_builder()
        cls = b.get_message_class("test.User")
        expected = cls(name="Alice")
        base = equals_proto(expected)
        partial = base.partially()
        assert base is not partial

        actual = cls(name="Alice", email="extra@x")
        # base (full) fails on the extra; partial passes — proving base was not
        # mutated by deriving the partial matcher.
        with pytest.raises(AssertionError):
            assert_that(actual, base)
        assert_that(actual, partial)


# ---------------------------------------------------------------------------
# Directionality (KTD-5): expected -> left
# ---------------------------------------------------------------------------


class TestDirectionality:
    """``equals_proto(expected)`` maps expected to the differ's left side."""

    def test_partial_suppresses_actual_only_extras(self) -> None:
        b = _user_builder()
        cls = b.get_message_class("test.User")
        expected = cls(name="Alice")
        actual = cls(name="Alice", email="x@y", id=42)
        assert_that(actual, equals_proto(expected).partially())

    def test_partial_still_reports_actual_missing(self) -> None:
        b = _user_builder()
        cls = b.get_message_class("test.User")
        expected = cls(name="Alice", email="x@y")
        actual = cls(name="Alice")
        with pytest.raises(AssertionError):
            assert_that(actual, equals_proto(expected).partially())


# ---------------------------------------------------------------------------
# Predicate exceptions propagate (KTD-10 / SWI-3) — same as agnostic surface
# ---------------------------------------------------------------------------


class TestPredicateExceptionsPropagate:
    """A raising ignore predicate surfaces the author's exception, not AssertionError."""

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
            assert_that(actual, equals_proto(expected).ignoring(boom))
