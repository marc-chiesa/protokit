"""Shared internal fidelity measurement — the unmodeled-byte delta.

Extracted from :mod:`protokit.storage._columnar` so both the columnar sink and
the forensics ``match`` ranking depend on one named seam rather than reaching
into another module's private symbol. The function, signature, and
``EncodeError -> None`` contract are unchanged from the original
``_columnar._unmodeled_byte_delta`` (``_columnar`` re-imports it under that name
so its call sites and the existing ``tests/storage/test_columnar_fidelity.py``
keep resolving it).
"""

from __future__ import annotations

from google.protobuf.message import EncodeError, Message


def unmodeled_byte_delta(message: Message) -> int | None:
    """Wire bytes ``message`` carried that its descriptor does not model.

    The serialized-size difference between ``message`` and a copy with its
    unknown-field set discarded — recursively, into submessages, repeated
    elements, and map entries (``DiscardUnknownFields`` clears the whole tree). A
    non-zero delta means the message carried wire data outside the descriptor: a
    proto2 out-of-range closed-enum value (which the runtime relegates to the
    unknown-field set) or an *undeclared* unknown/extension field. ``0`` means
    the descriptor modeled every byte — including proto3 open-enum out-of-range
    values, which are preserved as the field value, not relegated.

    Returns ``None`` ("cannot measure") when the message is not fully
    initialized — a proto2 message missing a required field. A declared proto2
    extension (read into ``Extensions[...]`` with an empty unknown set) and a
    group field are invisible to this probe; that is a documented non-goal —
    the structural / wire-walker channels cover them.

    **The initialization test is an explicit predicate, not an exception**
    (KTD6, V1). This previously inferred "cannot measure" from ``ByteSize``
    raising ``EncodeError``, which is upb behaviour and upb behaviour only:
    under the pure-Python runtime ``ByteSize`` returns ``0`` for an
    uninitialized message and raises nothing, so the probe returned ``0`` —
    "the descriptor modeled every byte" — for a message it had in fact not
    measured. That is a fail-open of the exact shape this release exists to
    close, and it degraded *silently*, since a backend that never raises makes
    the ``except`` arm dead code rather than a visible error.

    ``IsInitialized()`` answers the same question directly and agrees across
    both backends. The ``except EncodeError`` arm is kept below it as a
    belt-and-braces guard for any other encode failure, not as the signal.
    """
    if not message.IsInitialized():
        return None
    try:
        # Typed locals: protobuf ships no stubs, so ByteSize() is Any; annotate so
        # mypy --strict (warn_return_any) sees an int subtraction, not Any.
        before: int = message.ByteSize()
        clone = type(message)()
        clone.CopyFrom(message)
        clone.DiscardUnknownFields()
        after: int = clone.ByteSize()
        return before - after
    except EncodeError:
        return None
