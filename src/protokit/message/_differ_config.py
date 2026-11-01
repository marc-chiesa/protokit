"""A differencer's configuration, frozen when a comparison starts.

:meth:`MessageDifferencer.compare` takes a :class:`DifferConfig` of its
settings and keeps it, with the two descriptor pools, in the
:class:`CallContext` for that call. Hooks read the pools from the context, so
a ``compare()`` nested inside a hook installs its own context and restores the
caller's when it returns.

Set pairing (``treat_as_set``) decides element equality with a trial
comparison under :meth:`DifferConfig.for_trial`: the caller's ignore rules,
presence mode and nested set and map policies, with floats exact, no hooks and
partial off. Exact floats keep pairing an equivalence relation, so the pairing
does not depend on element order. Hooks then run once, on the chosen pairs.

This module imports nothing from ``differ``. The differ builds a config from
itself and a trial differencer from a config.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any

from protokit.message._selector import FieldSelector
from protokit.message.comparators import FloatComparison, FloatConfig, MessageFieldComparison
from protokit.message.model import FieldHook, FieldPath, MessageValidateHook

_EXACT_FLOATS = FloatConfig(mode=FloatComparison.EXACT)


@dataclass(frozen=True)
class DifferConfig:
    """Every setting that decides what a comparison reports.

    Each field mirrors the ``MessageDifferencer`` attribute of the same name
    (with its leading underscore dropped), copied when ``compare()`` starts.
    """

    ignore_names: frozenset[str]
    ignore_paths: tuple[FieldPath, ...]
    ignore_selectors: tuple[FieldSelector, ...]
    treat_as_map: tuple[tuple[str, str], ...]
    treat_as_map_paths: tuple[tuple[FieldPath, str], ...]
    treat_as_set_selectors: tuple[FieldSelector, ...]
    partial: bool
    presence_mode: MessageFieldComparison
    float_config: FloatConfig
    float_overlays: tuple[tuple[FieldSelector, FloatConfig], ...]
    max_depth: int | None
    strict_schema: bool
    validate_hooks: tuple[FieldHook, ...]
    compare_hooks: tuple[FieldHook, ...]
    report_hooks: tuple[FieldHook, ...]
    message_validate_hooks: tuple[MessageValidateHook, ...]

    def for_trial(self) -> DifferConfig:
        """This configuration as set pairing compares candidate elements.

        Ignore rules, presence mode, nested set and map policies and strict
        schema carry over. Floats compare exactly, with no per-field tolerance.
        There is no depth limit: elements that differ below ``max_depth`` do
        not pair, and the walk of a chosen pair stops at the limit as usual.
        There are no hooks, and partial comparison is off, because partial
        does not apply inside a set field. Applying it twice gives the same
        configuration.
        """
        return dataclasses.replace(
            self,
            max_depth=None,
            partial=False,
            float_config=_EXACT_FLOATS,
            float_overlays=(),
            validate_hooks=(),
            compare_hooks=(),
            report_hooks=(),
            message_validate_hooks=(),
        )


@dataclass
class CallContext:
    """The state of one ``compare()`` call.

    Attributes:
        left_pool: The left message's descriptor pool, which hooks read.
        right_pool: The right message's descriptor pool.
        config: The configuration the call started with. ``None`` only in
            :data:`IDLE`, the context of a differencer between calls.
        trial: The trial differencer and its context, built the first time
            set pairing needs them in this call (see ``differ._trial_pairs``).
        in_trial: True for a trial's own context. A trial needs only whether
            elements pair, so it does not walk the pairs it chooses: they
            already showed nothing but schema changes, which a trial accepts.
            Walking them again would repeat every nested trial at each level.
        truncated_paths: Where ``max_depth`` cut the call's walk off. A chosen
            set pair walked by a second differencer (under partial) adds to it.
    """

    left_pool: Any
    right_pool: Any
    config: DifferConfig | None = None
    trial: tuple[Any, CallContext] | None = None
    in_trial: bool = False
    truncated_paths: list[FieldPath] = dataclasses.field(default_factory=list)


# The context of a differencer that is not comparing: no pools, no config.
IDLE = CallContext(left_pool=None, right_pool=None)
