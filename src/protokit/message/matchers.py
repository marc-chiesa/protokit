"""Public, framework-agnostic proto matchers over the comparison engine.

This module is the front-end the brainstorm calls for: a single-call
:func:`proto_match`, a fluent :func:`expect_proto` builder, and the frozen
:class:`MatchPolicy` both produce. Every front-end here builds a
``MatchPolicy``, hands it to the *single* mapping point
(:func:`_build_differ`), runs one freshly-built :class:`MessageDifferencer`,
and on a non-empty :class:`DiffResult` raises :class:`AssertionError` whose
message is the engine's existing per-field rich diff (KTD-4, SWI-1).

Directionality is load-bearing (KTD-5 / SWI-1): ``expected`` maps to the
differ's ``left`` and ``actual`` maps to its ``right``, matching
``MessageDifferencer.compare(left, right)``'s expected=left contract. Partial
scope, presence ADDED/REMOVED, and set-leftover sides all assume that mapping.

The matcher never reaches into private differ state: ``MatchPolicy`` is the
only representation a front-end holds, and ``_build_differ`` is the only place
that calls the differ's builder methods (SWI-2). A *fresh* differ is built per
comparison because ``MessageDifferencer`` stores per-run pool state and is
documented not thread-safe (KTD-5) — a cached/shared differ would reintroduce a
race under parametrized/concurrent test use.

This module is strict-typed (``mypy --strict``) and gated by
``tests/test_static_analysis.py``.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from protokit.message._selector import FieldSelector, SelectorSpec
from protokit.message.comparators import FloatComparison, MessageFieldComparison
from protokit.message.differ import MessageDifferencer
from protokit.message.pytest_plugin import render_diff_lines

if TYPE_CHECKING:  # pragma: no cover — typing-only import
    from google.protobuf.message import Message


__all__ = [
    "Approx",
    "MatchPolicy",
    "MatcherError",
    "expect_proto",
    "proto_match",
]


class MatcherError(Exception):
    """Base class for matcher-configuration errors (not match failures).

    A *match failure* — ``actual`` does not match ``expected`` under the
    policy — is always raised as a plain :class:`AssertionError` so it reads
    naturally in any test framework. ``MatcherError`` is reserved for
    *configuration* problems detected while building or validating a
    :class:`MatchPolicy` (e.g. a contradictory paired-field config), so callers
    can distinguish "the policy is malformed" from "the messages differ".
    """


@dataclass(frozen=True)
class Approx:
    """Float-approximation tolerance for the matcher surface.

    A small ergonomic holder mapped onto the engine's float-comparison config.
    ``APPROXIMATE`` mode is implied — constructing an ``Approx`` *is* the
    request for tolerant float comparison. Absolute ``margin`` and relative
    ``fraction`` are combined as a logical OR (the engine's semantics): two
    floats are equal if ``|a - b| <= margin`` OR
    ``|a - b| <= fraction * max(|a|, |b|)``.

    Used both globally (``proto_match(..., approx=Approx(margin=1e-6))``) and
    per field as the second element of an overlay tuple
    (``approx=(("ratio", Approx(margin=1e-6)),)``).

    Attributes:
        margin: Absolute tolerance. Defaults to the engine default ``1e-9``.
        fraction: Relative tolerance. Defaults to the engine default ``1e-6``.
    """

    margin: float = 1e-9
    fraction: float = 1e-6


# A per-field approx overlay: a selector spec paired with its tolerance.
ApproxOverlay = tuple[SelectorSpec, Approx]


@dataclass(frozen=True)
class MatchPolicy:
    """Immutable description of how a matcher compares two messages.

    The single representation every front-end (``proto_match``,
    ``expect_proto``, and the optional PyHamcrest adapter) builds and hands to
    :func:`_build_differ`. Each field maps to exactly one
    :class:`MessageDifferencer` builder call (SWI-2).

    Collection inputs are snapshotted to immutable tuples in
    :meth:`__post_init__` (frozen-dataclass discipline — see
    ``docs/solutions/best-practices/frozen-dataclass-mutable-fields-need-post-init-snapshot-2026-05-02.md``)
    so mutating a list a caller passed in does not retroactively change the
    policy. Paired-field invariants are enforced there too
    (``…paired-field-invariant-post-init-2026-05-11.md``).

    Attributes:
        partial: When ``True``, only fields present on ``expected`` (the
            differ's ``left``) are compared; extra fields on ``actual`` are not
            differences (R5/U4). Defaults to ``False`` (full comparison).
        as_set: Selectors for repeated fields compared order-independently as a
            multiset, with no key (R6/U3). Each is a bare name / dotted path,
            a ``(FieldDescriptor, FieldPath) -> bool`` predicate, or a
            :class:`FieldSelector`. Snapshotted to a tuple.
        ignore: Selectors whose matching fields are not compared (R8/U2), same
            spec forms as ``as_set``. Snapshotted to a tuple.
        presence: ``MessageFieldComparison.EQUIVALENT`` (default — set-to-default
            ≈ unset) or ``MessageFieldComparison.EQUAL`` (distinguish them where
            presence is observable) (R10/U5). The plan's "PresenceMode" wording
            is reconciled by reusing this existing engine enum directly.
        approx: Optional GLOBAL float tolerance applied to every float/double
            field (R11/U6).
        approx_overlays: Per-field float tolerance overlays — ``(selector,
            Approx)`` tuples layered OVER ``approx`` / the engine default
            (KTD-6). Consulted in registration order; the first whose selector
            matches a float field supplies its tolerance. Snapshotted to a
            tuple.
    """

    partial: bool = False
    as_set: tuple[SelectorSpec, ...] = ()
    ignore: tuple[SelectorSpec, ...] = ()
    presence: MessageFieldComparison = MessageFieldComparison.EQUIVALENT
    approx: Approx | None = None
    approx_overlays: tuple[ApproxOverlay, ...] = ()

    def __post_init__(self) -> None:
        """Snapshot mutable inputs to tuples and validate paired invariants.

        ``frozen=True`` blocks attribute rebinding only, not nested mutation of
        a passed-in list; coercing the collection inputs to tuples here means a
        caller's later ``list.append`` cannot alter this policy. The
        ``presence`` invariant rejects a non-``MessageFieldComparison`` value
        before it silently no-ops at compare time.
        """
        object.__setattr__(self, "as_set", tuple(self.as_set))
        object.__setattr__(self, "ignore", tuple(self.ignore))
        object.__setattr__(self, "approx_overlays", tuple(self.approx_overlays))

        # Paired-field invariant: ``presence`` discriminates how float/message
        # presence is compared; an unrecognized value would silently behave as
        # EQUIVALENT at compare time. Reject it loudly at construction.
        if not isinstance(self.presence, MessageFieldComparison):
            raise MatcherError(
                "MatchPolicy.presence must be a MessageFieldComparison "
                f"(EQUAL or EQUIVALENT); got {self.presence!r}"
            )


def _build_differ(policy: MatchPolicy) -> MessageDifferencer:
    """Build a fresh, configured ``MessageDifferencer`` from a policy.

    The SINGLE mapping point from ``MatchPolicy`` to differ configuration
    (SWI-2): every policy field maps to exactly one builder call here and
    nowhere else. A new differ is constructed on every call because the differ
    is documented not thread-safe (KTD-5).

    Args:
        policy: The frozen policy describing the comparison.

    Returns:
        A configured ``MessageDifferencer`` ready for
        ``compare(expected, actual)`` (expected=left).
    """
    differ = MessageDifferencer()

    if policy.partial:
        differ.set_partial(True)

    if policy.ignore:
        differ.ignore_fields(*policy.ignore)

    for selector in policy.as_set:
        differ.treat_as_set(selector)

    differ.set_message_field_comparison(policy.presence)

    if policy.approx is not None:
        differ.set_float_comparison(
            FloatComparison.APPROXIMATE,
            fraction=policy.approx.fraction,
            margin=policy.approx.margin,
        )

    for selector, approx in policy.approx_overlays:
        differ.set_float_comparison(
            FloatComparison.APPROXIMATE,
            fraction=approx.fraction,
            margin=approx.margin,
            selector=selector,
        )

    return differ


def _assert_matches(policy: MatchPolicy, actual: Message, expected: Message) -> None:
    """Run the policy and raise ``AssertionError`` (rich diff) on mismatch.

    Maps ``expected`` -> the differ's ``left`` and ``actual`` -> its ``right``
    (KTD-5), so partial/presence/set directionality reads correctly. On a
    non-empty result the message is rendered by the shared
    :func:`render_diff_lines` — the same formatter the pytest ``==`` hook uses
    (KTD-4), reading only canonical ``left_value`` / ``right_value``.

    Predicate exceptions (in ``ignore`` / ``as_set`` selectors) propagate
    unchanged — they are author bugs, not match failures (KTD-10 / SWI-3).

    Args:
        policy: The comparison policy.
        actual: The message under test (mapped to the differ's ``right``).
        expected: The reference message (mapped to the differ's ``left``).

    Raises:
        AssertionError: If ``actual`` does not match ``expected`` under
            ``policy``. The message carries the per-field diff.
    """
    differ = _build_differ(policy)
    result = differ.compare(expected, actual)
    if not result.has_changes():
        return

    expected_type = expected.DESCRIPTOR.full_name
    actual_type = actual.DESCRIPTOR.full_name
    if expected_type == actual_type:
        header = f"proto match failed: expected != actual ({expected_type})"
    else:
        header = (
            f"proto match failed: expected != actual "
            f"({expected_type} != {actual_type}, cross-schema)"
        )

    raise AssertionError("\n".join(render_diff_lines(result, header)))


def _approx_from_kwargs(
    approx: Approx | None,
    margin: float | None,
    fraction: float | None,
) -> Approx | None:
    """Resolve the global-approx kwargs into a single ``Approx`` (or ``None``).

    ``proto_match`` accepts either an explicit ``approx=Approx(...)`` or the
    flat ``margin=`` / ``fraction=`` shorthand. This folds them into one value,
    rejecting the contradictory case where both an ``Approx`` and a flat kwarg
    are given.

    Args:
        approx: An explicit ``Approx`` instance, or ``None``.
        margin: Flat absolute-tolerance shorthand, or ``None``.
        fraction: Flat relative-tolerance shorthand, or ``None``.

    Returns:
        An ``Approx`` if any tolerance was requested, else ``None``.

    Raises:
        MatcherError: If ``approx`` is combined with ``margin`` / ``fraction``.
    """
    if approx is not None:
        if margin is not None or fraction is not None:
            raise MatcherError(
                "proto_match: pass either approx=Approx(...) or the flat "
                "margin=/fraction= shorthand, not both."
            )
        return approx
    if margin is None and fraction is None:
        return None
    return Approx(
        margin=1e-9 if margin is None else margin,
        fraction=1e-6 if fraction is None else fraction,
    )


def _as_tuple(spec: SelectorSpec | Iterable[SelectorSpec] | None) -> tuple[SelectorSpec, ...]:
    """Normalize a selector kwarg into a tuple of specs.

    A single spec (string, predicate, or :class:`FieldSelector`) and an
    iterable of specs are both accepted for ergonomics; ``None`` yields the
    empty tuple. A bare string is treated as one spec, not iterated
    character-by-character.

    Args:
        spec: ``None``, a single selector spec, or an iterable of specs.

    Returns:
        A tuple of selector specs.
    """
    if spec is None:
        return ()
    if isinstance(spec, str) or callable(spec) or isinstance(spec, FieldSelector):
        return (spec,)
    return tuple(spec)


def proto_match(
    actual: Message,
    expected: Message,
    *,
    partial: bool = False,
    as_set: SelectorSpec | Iterable[SelectorSpec] | None = None,
    ignore: SelectorSpec | Iterable[SelectorSpec] | None = None,
    presence: MessageFieldComparison | None = None,
    approx: Approx | None = None,
    margin: float | None = None,
    fraction: float | None = None,
) -> None:
    """Assert ``actual`` matches ``expected`` under a single-call policy.

    Builds a :class:`MatchPolicy` from the keyword knobs, runs one freshly
    configured :class:`MessageDifferencer`, and raises :class:`AssertionError`
    (carrying the engine's per-field rich diff) on mismatch. No raise means the
    messages match. This is the single-call sibling of the fluent
    :func:`expect_proto`; both produce identical semantics for the same policy
    (R2).

    Directional: ``expected`` is the reference (the differ's ``left``) and
    ``actual`` is under test (the differ's ``right``) — so ``partial=True``
    ignores fields present only on ``actual`` (KTD-5).

    Args:
        actual: The message under test.
        expected: The reference message.
        partial: Enable partial / sub-shape matching (R5).
        as_set: Repeated field selector(s) to compare order-independently as a
            multiset (R6). A single spec or an iterable of specs.
        ignore: Field selector(s) to exclude from comparison (R8). A single
            spec or an iterable of specs.
        presence: ``MessageFieldComparison.EQUAL`` to distinguish set-to-default
            from unset, or ``EQUIVALENT`` (the default) to collapse them (R10).
            ``None`` uses the policy default (``EQUIVALENT``).
        approx: Global float tolerance as an :class:`Approx`, or, for per-field
            tolerance, an iterable is NOT accepted here — use
            :func:`expect_proto`'s ``.approximately(selector=...)`` or build a
            :class:`MatchPolicy` directly for overlays.
        margin: Flat global absolute-tolerance shorthand (implies APPROXIMATE).
            Mutually exclusive with ``approx``.
        fraction: Flat global relative-tolerance shorthand (implies
            APPROXIMATE). Mutually exclusive with ``approx``.

    Raises:
        AssertionError: If ``actual`` does not match ``expected``.
        MatcherError: If the tolerance kwargs are contradictory.
    """
    resolved_approx = _approx_from_kwargs(approx, margin, fraction)
    policy = MatchPolicy(
        partial=partial,
        as_set=_as_tuple(as_set),
        ignore=_as_tuple(ignore),
        presence=MessageFieldComparison.EQUIVALENT if presence is None else presence,
        approx=resolved_approx,
    )
    _assert_matches(policy, actual, expected)


@dataclass(frozen=True)
class ProtoMatcher:
    """Fluent matcher accumulating a :class:`MatchPolicy` over ``expected``.

    Returned by :func:`expect_proto`. Each builder step
    (``.partially()``, ``.ignoring()``, …) returns a NEW ``ProtoMatcher`` with
    an updated policy — the builder is immutable, so a partially-configured
    matcher can be shared and branched without surprise. Terminate with
    :meth:`matches` / :meth:`assert_matches`, which run the same
    policy → differ → diff path as :func:`proto_match` (R2).

    Attributes:
        expected: The reference message all configured comparisons run against.
        policy: The accumulated comparison policy.
    """

    expected: Message
    policy: MatchPolicy = field(default_factory=MatchPolicy)

    def partially(self) -> ProtoMatcher:
        """Return a new matcher with partial / sub-shape scope enabled (R5)."""
        return self._with(partial=True)

    def ignoring(self, selector: SelectorSpec) -> ProtoMatcher:
        """Return a new matcher that also ignores ``selector`` (R8).

        Args:
            selector: A bare name / dotted path, a
                ``(FieldDescriptor, FieldPath) -> bool`` predicate, or a
                :class:`FieldSelector`.
        """
        return self._with(ignore=(*self.policy.ignore, selector))

    def as_set(self, selector: SelectorSpec) -> ProtoMatcher:
        """Return a new matcher that compares ``selector`` as a multiset (R6).

        Args:
            selector: A selector for a repeated field to compare
                order-independently with no key.
        """
        return self._with(as_set=(*self.policy.as_set, selector))

    def with_presence(self, presence: MessageFieldComparison) -> ProtoMatcher:
        """Return a new matcher with the given presence comparison mode (R10).

        Args:
            presence: ``MessageFieldComparison.EQUAL`` or ``EQUIVALENT``.
        """
        return self._with(presence=presence)

    def strict_presence(self) -> ProtoMatcher:
        """Return a new matcher with EQUAL presence (distinguish default/unset).

        Shorthand for ``.with_presence(MessageFieldComparison.EQUAL)`` (R10).
        """
        return self._with(presence=MessageFieldComparison.EQUAL)

    def approximately(
        self,
        *,
        margin: float | None = None,
        fraction: float | None = None,
        selector: SelectorSpec | None = None,
    ) -> ProtoMatcher:
        """Return a new matcher applying float tolerance (R11).

        With ``selector=None`` this sets the GLOBAL tolerance; with a
        ``selector`` it registers a per-field overlay layered over the global
        setting (KTD-6). Either ``margin`` or ``fraction`` (or both) may be
        given; omitted values fall back to the engine defaults.

        Args:
            margin: Absolute tolerance. Defaults to ``1e-9`` when omitted.
            fraction: Relative tolerance. Defaults to ``1e-6`` when omitted.
            selector: When given, scopes the tolerance to matching float fields
                as an overlay; when ``None``, sets the global tolerance.
        """
        approx = Approx(
            margin=1e-9 if margin is None else margin,
            fraction=1e-6 if fraction is None else fraction,
        )
        if selector is None:
            return self._with(approx=approx)
        return self._with(
            approx_overlays=(*self.policy.approx_overlays, (selector, approx)),
        )

    def matches(self, actual: Message) -> None:
        """Assert ``actual`` matches ``expected`` under the accumulated policy.

        Identical semantics to :func:`proto_match` for the same policy (R2):
        no raise on match, :class:`AssertionError` with the rich diff on
        mismatch.

        Args:
            actual: The message under test.

        Raises:
            AssertionError: If ``actual`` does not match ``expected``.
        """
        _assert_matches(self.policy, actual, self.expected)

    def assert_matches(self, actual: Message) -> None:
        """Alias for :meth:`matches`, for callers who prefer the verb.

        Args:
            actual: The message under test.

        Raises:
            AssertionError: If ``actual`` does not match ``expected``.
        """
        self.matches(actual)

    def _with(self, **changes: Any) -> ProtoMatcher:
        """Return a new matcher with ``policy`` fields replaced by ``changes``.

        The accumulation primitive: builds a fresh :class:`MatchPolicy` from the
        current one with the named fields overridden (re-running
        ``__post_init__`` snapshotting/validation), then wraps it in a new
        immutable ``ProtoMatcher``.
        """
        new_policy = dataclasses.replace(self.policy, **changes)
        return ProtoMatcher(expected=self.expected, policy=new_policy)


def expect_proto(expected: Message) -> ProtoMatcher:
    """Begin a fluent proto match against ``expected``.

    Returns an immutable :class:`ProtoMatcher`; chain knobs
    (``.partially()``, ``.ignoring(...)``, ``.as_set(...)``,
    ``.with_presence(...)`` / ``.strict_presence()``,
    ``.approximately(...)``) and terminate with ``.matches(actual)`` /
    ``.assert_matches(actual)``. Produces identical semantics to the
    single-call :func:`proto_match` for the same policy (R2).

    Args:
        expected: The reference message to match ``actual`` against.

    Returns:
        A :class:`ProtoMatcher` configured with the default (full, exact)
        policy.
    """
    return ProtoMatcher(expected=expected)
