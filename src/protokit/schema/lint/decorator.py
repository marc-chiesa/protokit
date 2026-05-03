"""``@lint_rule`` decorator — pure metadata attachment for D2 rule packs.

Mirrors compat's per-instance pattern at ``schema/checker.py:217-235``:
no process-global registry, no module-attribute side effects on the
importing module. The decorator simply constructs a
:class:`~protokit.schema.lint.model.LintRuleSpec` from the call-site
kwargs and attaches it to the decorated function as
``fn._lint_spec``. Rule pack modules then expose a ``RULES`` tuple
listing the decorated functions; the engine reads
``module.RULES`` (echoing compat's convention) and harvests each
function's ``_lint_spec`` per-instance.

Test isolation, ``importlib.reload`` semantics, and dynamic-module
patterns work by construction — there is no global state to
contaminate.

**Supported decoration sites.** Module-level functions only.
Methods, lambdas, ``functools.partial`` wrappers, and nested
functions are NOT supported (the engine has no contract for those
shapes). The decorator does not actively reject these sites; rule
authors who try them will discover the foot-gun at engine-load
time, when the engine reads ``fn._lint_spec`` from a function whose
shape doesn't match expectations.

**Async rejection.** ``async def`` rule callables and async-
generator rule callables are rejected at decoration time with a
clear ``TypeError``. The lint engine is sync-only (no ``await``
contract on rule fns); silently no-op'ing an async rule (which
would happen if the engine tried to call it and discarded the
returned coroutine) is the wrong default. Surfaces the error at
import time of the rule pack, not at engine.run() time.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any, cast

from protokit.schema.lint.model import (
    ElementKind,
    LintRuleSpec,
    LintSeverity,
)


def lint_rule(
    *,
    rule_id: str,
    severity: LintSeverity | dict[str, LintSeverity],
    profiles: tuple[str, ...],
    element: ElementKind,
    message_template: str | dict[str, str],
    source_spec: str = "",
) -> Callable[[Callable[..., None]], Callable[..., None]]:
    """Attach a ``LintRuleSpec`` to a rule callable.

    Construct via kwargs only — never positional. Decorator kwarg
    order and ``LintRuleSpec`` field order differ; using kwargs
    avoids positional drift if either order changes.

    The decorated function is returned unchanged except for an added
    ``_lint_spec`` attribute carrying the constructed
    ``LintRuleSpec``. Rule pack modules expose a module-level
    ``RULES = (decorated_fn_1, decorated_fn_2, ...)`` tuple; the
    engine reads that tuple via :meth:`LintEngine.load_rule_pack`.

    Args:
        rule_id: Globally unique id (typically
            ``"<category>/<short-name>"``, e.g.,
            ``"naming/snake-case-fields"``).
        severity: Default severity for this rule. Either a
            ``LintSeverity`` (single-kind rule) or a
            ``dict[violation_kind, LintSeverity]`` (multi-kind rule).
            Must share its shape with ``message_template`` (both
            single-kind or both multi-kind); the LintRuleSpec
            ``__post_init__`` enforces this.
        profiles: Tuple of profile names this rule belongs to by
            default. ``LintProfile.from_pack(module, name)`` reads
            this to derive a profile from a pack; the engine itself
            consults ``profile.rule_ids`` (R11), so this field is
            authoritative for "which profile am I in?" but not for
            "did the engine actually run me?".
        element: Which descriptor element kind this rule visits.
            Determines which ``*LintContext`` dataclass the engine
            constructs and passes to the rule callable.
        message_template: Format string (single-kind) or dict
            mapping ``violation_kind -> str`` (multi-kind). The
            engine interpolates ``LintFinding.params`` into this at
            output-rendering time. Must share its shape with
            ``severity``.
        source_spec: Optional human-readable spec reference (e.g.,
            an AIP URL or a section anchor). Empty by default.

    Returns:
        A decorator that, when applied to a sync rule callable,
        attaches the constructed ``LintRuleSpec`` and returns the
        function.

    Raises:
        TypeError: If the decorated callable is an ``async def``
            function (caught by ``inspect.iscoroutinefunction``) or
            an async generator (caught by
            ``inspect.isasyncgenfunction``). Lint rules must be sync;
            async support is a separate roadmap item.
        TypeError: From ``LintRuleSpec.__post_init__`` if
            ``severity`` and ``message_template`` shapes don't match
            (single-kind vs multi-kind dict).
    """

    def wrap(fn: Callable[..., None]) -> Callable[..., None]:
        if inspect.iscoroutinefunction(fn) or inspect.isasyncgenfunction(fn):
            raise TypeError(
                f"@lint_rule does not support async or async-generator "
                f"callables; got {fn.__module__}.{fn.__qualname__}. Lint "
                f"rules must be sync; see the async-plugin support TODO "
                f"for the planned roadmap."
            )

        spec = LintRuleSpec(
            rule_id=rule_id,
            severity=severity,
            profiles=profiles,
            source_spec=source_spec,
            element=element,
            message_template=message_template,
            fn=fn,
        )
        # The engine reads fn._lint_spec at load_rule_pack time. Functions
        # don't normally have this attribute; setattr keeps mypy strict
        # quiet at the assignment site, and downstream readers either use
        # getattr(fn, "_lint_spec") or cast through Any.
        fn._lint_spec = spec  # type: ignore[attr-defined]
        return fn

    return wrap


def get_lint_spec(fn: Any) -> LintRuleSpec:
    """Return the ``LintRuleSpec`` attached to a decorated rule fn.

    Convenience accessor that surfaces a clear error when ``fn`` is
    not ``@lint_rule``-decorated, instead of an opaque
    ``AttributeError`` deep in caller code. The engine and
    ``LintProfile.from_pack`` access ``fn._lint_spec`` directly today;
    this helper is provided for external callers (D7 plugin tooling,
    a future ``--list-rules`` CLI) that want a clear error message
    rather than a raw attribute miss.

    Args:
        fn: A function to inspect. Expected to carry a
            ``_lint_spec`` attribute set by the ``@lint_rule``
            decorator.

    Returns:
        The attached ``LintRuleSpec``.

    Raises:
        TypeError: If ``fn`` has no ``_lint_spec`` attribute (i.e.,
            wasn't decorated with ``@lint_rule``).
    """
    spec = getattr(fn, "_lint_spec", None)
    if spec is None:
        raise TypeError(
            f"{fn!r} is not @lint_rule-decorated; missing _lint_spec "
            f"attribute. Apply @lint_rule(...) before adding to "
            f"module.RULES."
        )
    return cast(LintRuleSpec, spec)
