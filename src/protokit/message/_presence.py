"""Field-presence helpers for EQUAL vs EQUIVALENT comparison (KTD-7 / U5).

This module holds the pure, descriptor-aware decision logic the engine consults
to reconcile two presence-comparison modes for *singular* fields:

* **EQUIVALENT** (the default) — a field set to its default value is treated as
  equal to an unset field. This collapses the "set-to-default vs unset"
  presence delta wherever the value carried is the field default.
* **EQUAL** (opt-in) — a presence-bearing field that is set on one side (even to
  its default) and unset on the other is a *presence difference*, regardless of
  the value.

The distinction is only meaningful where presence is *observable*: proto2
fields, proto3 ``optional`` fields, oneof members, and singular message fields —
all of which expose ``HasField``. proto3 *implicit-presence* scalars carry no
presence bit (``HasField`` raises), so a default value is indistinguishable from
unset; EQUAL is a documented NO-OP for them and this module reports them as
not-observable so the engine never fabricates presence (KTD-7).

Synthetic oneofs: proto3 ``optional`` fields are implemented as a
compiler-synthesized oneof named ``_<field>``. Presence is read here via the
*field's* ``HasField`` (``fd.has_presence`` is True for a proto3-optional
field), never by iterating oneof declarations — so the synthetic oneof is never
itself observed as a member-change. See
``docs/solutions/logic-errors/proto3-optional-synthetic-oneof-false-positive-lint-rule-2026-05-12.md``.

Reconciliation with the engine's existing message-field handling: the engine
already reports an empty-but-present singular *message* field (set to the
default instance on one side, unset on the other) as ADDED/REMOVED today. That
is EQUAL behavior already baked into ``_compare_message_field``. To avoid
double-reporting, the engine routes *only leaf (scalar/enum/bytes/float)*
presence-bearing fields through this module's :func:`presence_verdict`; message
fields keep their dedicated path, and EQUIVALENT mode is what *relaxes* that
path (so an empty-but-present message collapses with unset). See ``differ.py``.

This module is pure, strict-typed (``mypy --strict``), and gated by
``tests/meta/test_static_analysis.py``.
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover — typing-only imports
    from google.protobuf import descriptor as proto_descriptor
    from google.protobuf.message import Message


class PresenceVerdict(Enum):
    """The outcome of a single-field presence decision.

    Members:
        EQUAL_PRESENCE: Both sides agree on presence (both set or both
            unset). No presence difference; the engine should fall through
            to its ordinary value comparison.
        ADDED: The field is set on the right (actual) side and unset on the
            left (expected) side — a presence difference reported as
            :class:`~protokit.message.model.ChangeType.ADDED`.
        REMOVED: The field is set on the left (expected) side and unset on
            the right (actual) side — a presence difference reported as
            :class:`~protokit.message.model.ChangeType.REMOVED`.
        COLLAPSE: A one-sided presence delta that the active mode treats as
            equal (EQUIVALENT, set side carries the field default). No
            difference is emitted and the engine should NOT fall through to
            value comparison — the two sides are deemed equivalent.
    """

    EQUAL_PRESENCE = "EQUAL_PRESENCE"
    ADDED = "ADDED"
    REMOVED = "REMOVED"
    COLLAPSE = "COLLAPSE"


def is_set(msg: Message, fd: proto_descriptor.FieldDescriptor) -> bool:
    """Whether a presence-bearing singular field is set on ``msg``.

    Reads presence via ``HasField`` on the field directly. For a proto3
    ``optional`` field this consults its compiler-synthesized ``_<field>``
    oneof under the hood, but the synthetic oneof is never iterated or named
    here — presence is always read field-first, so the synthetic oneof cannot
    surface as a spurious member change (KTD-7).

    Args:
        msg: The parent message holding the field.
        fd: The field descriptor — MUST be presence-bearing (``fd.has_presence``
            is True: proto2 fields, proto3 ``optional`` fields, oneof members,
            and singular message fields); calling ``HasField`` on a
            non-presence field raises ``ValueError``.

    Returns:
        True if the field is set on ``msg``.
    """
    return bool(msg.HasField(fd.name))


def _is_default_value(msg: Message, fd: proto_descriptor.FieldDescriptor) -> bool:
    """Whether the (set) leaf field carries its type default value.

    Used only for EQUIVALENT mode, to decide whether a one-sided presence
    delta should collapse. Compares the field's current value to the
    descriptor's declared default. Not called for message fields (handled on
    their own path) — only scalar/enum/bytes/float leaves reach here.

    Args:
        msg: The parent message holding the field (the set side).
        fd: The leaf field descriptor.

    Returns:
        True if the field value equals its declared default.
    """
    return bool(getattr(msg, fd.name) == fd.default_value)


def presence_verdict(
    left_msg: Message,
    right_msg: Message,
    left_fd: proto_descriptor.FieldDescriptor,
    right_fd: proto_descriptor.FieldDescriptor,
    *,
    equal_mode: bool,
    left_set: bool | None = None,
    right_set: bool | None = None,
) -> PresenceVerdict:
    """Decide the presence relationship of a singular leaf field on both sides.

    This is the EQUAL-vs-EQUIVALENT decision for one presence-observable leaf
    (scalar/enum/bytes/float) field. It is consulted by the engine *before*
    value comparison; message fields use their own dedicated path and never
    reach here (to avoid double-reporting the empty-but-present exception).

    Decision table (both descriptors presence-observable):

    ===========  ===========  =================  =================
    left set?    right set?   EQUIVALENT          EQUAL
    ===========  ===========  =================  =================
    no           no           EQUAL_PRESENCE      EQUAL_PRESENCE
    yes          yes          EQUAL_PRESENCE      EQUAL_PRESENCE
    no           yes          ADDED if right is   ADDED
                              non-default, else
                              COLLAPSE
    yes          no           REMOVED if left is  REMOVED
                              non-default, else
                              COLLAPSE
    ===========  ===========  =================  =================

    ``EQUAL_PRESENCE`` means "presence agrees — fall through to value
    comparison". ``COLLAPSE`` (EQUIVALENT only) means "the set side carries the
    default, treat as equal, emit nothing AND do not value-compare".

    The set-to-non-default-vs-unset case reports ADDED/REMOVED in BOTH modes —
    that is the engine's existing, regression-pinned behavior, preserved
    identically. The mode choice only governs the *set-to-default*-vs-unset
    case: EQUIVALENT collapses it (today's documented intent), EQUAL reports it.

    Args:
        left_msg: The expected (left) parent message.
        right_msg: The actual (right) parent message.
        left_fd: The left-side leaf field descriptor (presence-observable).
        right_fd: The right-side leaf field descriptor (presence-observable).
        equal_mode: True for EQUAL semantics, False for EQUIVALENT (default).
        left_set: The left-side presence, if the caller already computed it via
            ``HasField``; ``None`` (the default) recomputes it here. Lets a
            caller that has the booleans avoid a redundant ``HasField`` pair.
        right_set: The right-side presence, same contract as ``left_set``.

    Returns:
        A :class:`PresenceVerdict` for the field.
    """
    if left_set is None:
        left_set = is_set(left_msg, left_fd)
    if right_set is None:
        right_set = is_set(right_msg, right_fd)

    if left_set == right_set:
        # Both set or both unset: presence agrees. Both-set falls through to
        # value comparison; both-unset is equal there too.
        return PresenceVerdict.EQUAL_PRESENCE

    if not left_set and right_set:
        if equal_mode:
            return PresenceVerdict.ADDED
        # EQUIVALENT: a non-default value is a real ADD; a default value
        # collapses (set-to-default ≈ unset).
        if _is_default_value(right_msg, right_fd):
            return PresenceVerdict.COLLAPSE
        return PresenceVerdict.ADDED

    # left_set and not right_set
    if equal_mode:
        return PresenceVerdict.REMOVED
    if _is_default_value(left_msg, left_fd):
        return PresenceVerdict.COLLAPSE
    return PresenceVerdict.REMOVED
