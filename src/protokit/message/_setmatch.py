"""Greedy multiset pairing for keyless ("set") repeated-field comparison.

This module holds ONLY the pairing algorithm (KTD-8 / U3). It pairs the
elements of two repeated fields order-independently, as multisets, using an
**injected element-equality callable** — it never compares elements itself.

Why injected equality? Deciding whether two repeated *message* elements are
equal requires the differ engine's descriptor-aware comparison (cross-pool
name-matching, enum wire-compatibility, presence semantics). A pure helper
cannot reproduce that, so the caller (``differ.py``) supplies an
``equal_fn(left_elem, right_elem) -> bool`` backed by the engine. The helper
therefore stays pure, typed, and free of engine imports; the engine stays the
single source of equality truth, matching ``compare()`` semantics exactly.

Cost: the greedy scan does up to ``O(n * m)`` calls to ``equal_fn`` (n left,
m right elements). For message elements each call is itself a sub-comparison,
so the real cost is ``O(n * m)`` *sub-comparisons*, not scalar compares. This
is acceptable for test-sized repeated fields, which is the intended use; it is
NOT a general-purpose large-collection diff.

Correctness contract (load-bearing, KTD-8): ``equal_fn`` MUST implement a true
equivalence relation — STRICT exact equality, without tolerance/partial/other
per-element policies. That keeps the matched/unmatched partition
order-independent: the *counts* paired within each equivalence class are the
same regardless of element order on either side. Which specific equal instance
is named as a leftover when duplicates exist is unspecified (fine for v1).

This module is strict-typed (``mypy --strict``) and gated by
``tests/meta/test_static_analysis.py``.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TypeVar

_L = TypeVar("_L")
_R = TypeVar("_R")

# An element-equality decision over one left element and one right element.
# Injected by the engine so set-membership equality matches ``compare()``.
ElementEqual = Callable[[_L, _R], bool]


def greedy_multiset_pairing(
    left_elems: Sequence[_L],
    right_elems: Sequence[_R],
    equal_fn: ElementEqual[_L, _R],
) -> tuple[list[tuple[int, int]], list[int], list[int]]:
    """Pair two element sequences as multisets via a greedy first-fit scan.

    For each left element (in order), the first not-yet-matched right element
    for which ``equal_fn`` returns True is claimed as its match. Right
    elements already claimed by an earlier left element cannot match again, so
    duplicates are handled as a multiset: ``["x", "x"]`` against ``["x"]``
    pairs exactly one ``"x"`` and leaves the other left ``"x"`` unmatched.

    The leftovers are returned as index lists so the caller can emit
    REMOVED differences for the expected (left) side and ADDED differences for
    the actual (right) side, reusing its existing element ``Difference`` shape.

    Args:
        left_elems: The expected-side (left) elements, in their declared order.
        right_elems: The actual-side (right) elements, in their declared order.
        equal_fn: A ``(left_elem, right_elem) -> bool`` callable deciding
            element equality. MUST be a strict equivalence relation (see the
            module docstring) for the partition to be order-independent. Any
            exception it raises propagates unchanged.

    Returns:
        A ``(matched_pairs, expected_unmatched_indices, actual_unmatched_indices)``
        tuple:

        * ``matched_pairs`` — ``(left_index, right_index)`` pairs, one per
          paired left element, in ascending left-index order.
        * ``expected_unmatched_indices`` — indices into ``left_elems`` with no
          match (report as REMOVED), ascending.
        * ``actual_unmatched_indices`` — indices into ``right_elems`` not
          claimed by any left element (report as ADDED), ascending.
    """
    matched_pairs: list[tuple[int, int]] = []
    expected_unmatched: list[int] = []
    # Track which right indices have been claimed; a list-of-bool keeps the
    # scan simple and the leftover computation a single ascending pass.
    right_claimed: list[bool] = [False] * len(right_elems)

    for li, left_elem in enumerate(left_elems):
        found = False
        for ri, right_elem in enumerate(right_elems):
            if right_claimed[ri]:
                continue
            if equal_fn(left_elem, right_elem):
                right_claimed[ri] = True
                matched_pairs.append((li, ri))
                found = True
                break
        if not found:
            expected_unmatched.append(li)

    actual_unmatched = [ri for ri, claimed in enumerate(right_claimed) if not claimed]
    return matched_pairs, expected_unmatched, actual_unmatched
