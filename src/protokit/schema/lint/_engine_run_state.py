"""Per-engine, per-run mutable state for rule callables.

Rule callables are module-level functions, so state that must outlive a
single ``__call__`` — a dedup set built across a walk, a lookup index
computed once per file — has nowhere to live but module scope. Module
scope leaks two ways: across concurrent :class:`~protokit.schema.lint.engine.LintEngine`
instances, and across repeated ``engine.run()`` calls on the same engine
(the CLI runs once per process, but MCP / IDE runtimes recycle engines).

:func:`per_run_state` closes both. Entries live in a caller-owned
:class:`weakref.WeakKeyDictionary` keyed on the engine, so state is
collected with the engine and never shared between engines; the stored
``id(engine._runtime_warnings)`` is the run epoch, because ``engine.run()``
assigns a *fresh* list there at every run entry, so a changed id means a
new run and the value is rebuilt.

This module is the shared extraction the third caller triggered — see
``docs/solutions/best-practices/weakkeydict-plus-id-resettable-attr-per-engine-per-run-state-2026-05-20.md``,
whose "third instance promotes to a shared helper" rule this satisfies.
Callers today: ``rules/options/field_behavior`` and ``_custom_rules``
(unresolved-extension dedup sets) and ``rules/options/_comments`` (the
per-file leading-comment index).

Any regression test for a caller MUST call ``engine.run()`` **twice** on
one engine and assert the second run behaves like the first; a
single-run test passes even against the module-level-``set`` anti-pattern.
"""

from __future__ import annotations

import weakref
from collections.abc import Callable
from typing import TYPE_CHECKING, TypeVar

from protokit.schema.lint.model import LintRuleError

if TYPE_CHECKING:
    from protokit.schema.lint.engine import LintEngine

#: Callers declare their store as
#: ``weakref.WeakKeyDictionary[LintEngine, tuple[int, <state>]]`` — the value
#: pairs the run epoch (``id(engine._runtime_warnings)``) with the state.
_T = TypeVar("_T")


def per_run_state(
    store: weakref.WeakKeyDictionary[LintEngine, tuple[int, _T]],
    engine: LintEngine,
    factory: Callable[[], _T],
) -> _T:
    """Return ``engine``'s state in ``store``, rebuilt when a new run started.

    Args:
        store: A module-level ``WeakKeyDictionary`` owned by the caller, so
            unrelated callers never share an entry.
        engine: The engine whose current ``run()`` scopes the state.
        factory: Builds a fresh value for a new engine or a new run. Called
            at most once per (engine, run).

    Returns:
        The value ``factory`` produced for this engine's current run — the
        same object on every call within that run.
    """
    current_run = id(engine._runtime_warnings)
    state = store.get(engine)
    if state is None or state[0] != current_run:
        fresh = factory()
        store[engine] = (current_run, fresh)
        return fresh
    return state[1]


def engine_for_ctx(ctx: object, rule_id: str) -> LintEngine:
    """Return the active :class:`LintEngine` behind a rule context.

    ``LintContext`` exposes no public ``engine`` attribute, but the engine
    threads itself in via ``ctx._emit_fn`` — its own bound ``_emit`` method,
    whose ``__self__`` is the engine. This keeps built-in rules off a public
    surface change on the context.

    Args:
        ctx: Any lint context carrying the engine-injected ``_emit_fn``.
        rule_id: Named in the failure message so the broken rule is obvious.

    Raises:
        LintRuleError: if ``ctx._emit_fn`` is not a bound method, meaning the
            engine's context-construction shape changed. ``LintRuleError``
            (not a bare ``RuntimeError``) routes the failure through the
            engine's ``rule_exception`` channel, so one structurally broken
            rule records a runtime warning instead of crashing ``run()``.
    """
    engine = getattr(getattr(ctx, "_emit_fn", None), "__self__", None)
    if engine is None:
        raise LintRuleError(
            f"{rule_id} could not resolve the active LintEngine through "
            "ctx._emit_fn. The context shape changed; update "
            "protokit.schema.lint._engine_run_state.engine_for_ctx accordingly."
        )
    return engine  # type: ignore[no-any-return]
