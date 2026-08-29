"""Plugin API for custom compatibility rules.

A plugin is an emit-style callable: it receives a context object that
carries everything the rule needs (descriptors, pools, path) plus an
``emit()`` method to record findings. Compared to the raw return-style
rules in ``schema.rules``, plugins are the user-facing surface — easier
to write, less coupled to the engine's internal call shape.

Example::

    def validate_max_len(ctx: FieldRuleContext) -> None:
        if ctx.old_field is None or ctx.new_field is None:
            return
        # Look up a custom option via the field's pool, etc.
        ctx.emit(severity=Severity.POLICY,
                 message="validation max_len changed")

    checker.register_field_rule("validate_max_len", validate_max_len)

Rule packs (modules with a ``RULES`` list of ``(rule_id, plugin_fn)``
tuples) are loaded via ``SchemaChecker.load_rule_pack(module)``.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import ModuleType
from typing import Callable, Protocol

from google.protobuf import descriptor as proto_descriptor
from google.protobuf import descriptor_pool

from protokit.message.model import FieldPath
from protokit.schema.model import Direction, Finding, Severity


# ---------------------------------------------------------------------------
# Emit callback signature
# ---------------------------------------------------------------------------

# Engine-injected closure that records a Finding. Plugins should not
# call this directly — use ``ctx.emit(...)`` which fills in path and
# rule_id from the context.
EmitFn = Callable[..., None]


def _validate_emit_args(severity: Severity, direction: Direction) -> None:
    """Type-check the arguments to ``ctx.emit(...)``.

    Raised at emit time so a plugin that passes raw strings (or any
    non-enum value) for severity/direction fails loudly instead of
    silently escaping profile filtering or crashing later in JSON
    rendering.

    Args:
        severity: Candidate severity value.
        direction: Candidate direction value.

    Raises:
        TypeError: If either argument is not the correct enum type.
    """
    if not isinstance(severity, Severity):
        raise TypeError(
            f"emit(severity=...) must be a Severity enum member, "
            f"got {type(severity).__name__}: {severity!r}"
        )
    if not isinstance(direction, Direction):
        raise TypeError(
            f"emit(direction=...) must be a Direction enum member, "
            f"got {type(direction).__name__}: {direction!r}"
        )


# ---------------------------------------------------------------------------
# Field plugin context
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FieldRuleContext:
    """Argument passed to a field-level plugin.

    Either ``old_field`` or ``new_field`` may be ``None``: ``None`` on
    the old side means the field was added in the new schema, ``None``
    on the new side means it was removed.

    Plugins call ``ctx.emit(...)`` to record findings; the engine
    handles path and rule_id wiring.

    ``path`` is not a stable input to branch on: when the containing
    message type is reachable by several paths, the plugin runs at
    only one of them and its findings are replayed under the others.
    See ``SchemaChecker.register_field_rule`` for the full contract.

    Attributes:
        path: Dotted ``FieldPath`` to the field being inspected. Any
            finding emitted via ``self.emit(...)`` inherits this path
            — and may be replayed under sibling paths, so treat it as
            one representative location, not the only one.
        old_field: Field descriptor from the old schema, or ``None`` if
            the field was added in the new schema.
        new_field: Field descriptor from the new schema, or ``None`` if
            the field was removed in the new schema.
        old_pool: Descriptor pool the old schema was resolved from.
            Useful for cross-extension lookup (e.g., resolving custom
            options registered in the same pool).
        new_pool: Descriptor pool the new schema was resolved from.
        _emit_fn: Engine-injected closure that records findings into
            the report. Do not call directly — use ``self.emit(...)``.
    """

    path: FieldPath
    old_field: proto_descriptor.FieldDescriptor | None
    new_field: proto_descriptor.FieldDescriptor | None
    old_pool: descriptor_pool.DescriptorPool
    new_pool: descriptor_pool.DescriptorPool
    _emit_fn: EmitFn

    def emit(
        self,
        *,
        severity: Severity,
        message: str,
        direction: Direction = Direction.BOTH,
    ) -> None:
        """Record a finding at the current field path.

        The emitted ``Finding`` reuses ``self.path`` and is tagged
        with the rule_id under which the plugin was registered.

        Args:
            severity: Classification of the finding's seriousness.
                Must be a ``Severity`` enum member.
            message: Human-readable explanation; appears in CLI/log
                output and JSON reports.
            direction: Direction of compatibility break. Defaults to
                ``Direction.BOTH`` which is appropriate for symmetric
                concerns. Use ``BACKWARD`` for old-consumer breaks
                and ``FORWARD`` for new-consumer breaks. Must be a
                ``Direction`` enum member.

        Raises:
            TypeError: If ``severity`` or ``direction`` is not the
                correct enum type.
        """
        _validate_emit_args(severity, direction)
        self._emit_fn(
            path=self.path,
            severity=severity,
            message=message,
            direction=direction,
        )


# ---------------------------------------------------------------------------
# Message plugin context
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MessageRuleContext:
    """Argument passed to a message-level plugin.

    **Both descriptors are always present.** The traversal is pair-driven:
    it only descends into a field whose type is a message on *both* sides,
    so a message type reachable from only one schema is never visited. Such
    a type surfaces through the built-in field rules as an added or removed
    *field*, not as a one-sided message visit. The ``| None`` in the
    annotations is structural headroom for a future traversal that can
    deliver one-sided visits; do not write a plugin that depends on being
    called with a ``None`` side, because it never is.

    The path points at the message itself, not a particular field —
    emitted findings inherit that path.

    ``path`` is not a stable input to branch on: the plugin runs once
    per message type pair, at whichever path the traversal reached it
    first, and its findings are replayed under every other path the
    pair appears at. See ``SchemaChecker.register_field_rule`` for the
    full contract.

    Attributes:
        path: Dotted ``FieldPath`` to the message being inspected.
            For the top-level message this is the empty path. One
            representative location, not necessarily the only one the
            finding is reported at.
        old_descriptor: Message descriptor from the old schema. Never
            ``None`` today — see the note above.
        new_descriptor: Message descriptor from the new schema. Never
            ``None`` today — see the note above.
        old_pool: Descriptor pool the old schema was resolved from.
        new_pool: Descriptor pool the new schema was resolved from.
        _emit_fn: Engine-injected closure that records findings.
            Do not call directly — use ``self.emit(...)``.
    """

    path: FieldPath
    old_descriptor: proto_descriptor.Descriptor | None
    new_descriptor: proto_descriptor.Descriptor | None
    old_pool: descriptor_pool.DescriptorPool
    new_pool: descriptor_pool.DescriptorPool
    _emit_fn: EmitFn

    def emit(
        self,
        *,
        severity: Severity,
        message: str,
        direction: Direction = Direction.BOTH,
    ) -> None:
        """Record a finding at this message's path.

        Args:
            severity: Classification of the finding's seriousness.
                Must be a ``Severity`` enum member.
            message: Human-readable explanation.
            direction: Direction of compatibility break; defaults to
                ``Direction.BOTH``. Must be a ``Direction`` enum
                member.

        Raises:
            TypeError: If ``severity`` or ``direction`` is not the
                correct enum type.
        """
        _validate_emit_args(severity, direction)
        self._emit_fn(
            path=self.path,
            severity=severity,
            message=message,
            direction=direction,
        )


# ---------------------------------------------------------------------------
# Plugin signatures
# ---------------------------------------------------------------------------


class FieldPlugin(Protocol):
    """Structural type for field-level plugins.

    A field plugin is any callable matching ``(FieldRuleContext) ->
    None``. Implementations inspect ``ctx`` (descriptors, pools, path)
    and call ``ctx.emit(...)`` zero or more times to record findings.
    """

    def __call__(self, ctx: FieldRuleContext) -> None:
        """Inspect a field-level context and emit findings.

        Args:
            ctx: The current field's context with old/new descriptors,
                pools, and path. Use ``ctx.emit(...)`` to record findings.
        """
        ...


class MessagePlugin(Protocol):
    """Structural type for message-level plugins.

    A message plugin is any callable matching
    ``(MessageRuleContext) -> None``. Fires once per ``(old, new)``
    message type pair (including the root) before the engine descends
    into fields, and must be path-independent — see
    ``SchemaChecker.register_field_rule`` for the full contract. Only
    pairs present on both sides are visited; see
    :class:`MessageRuleContext` for why there are no one-sided visits.
    """

    def __call__(self, ctx: MessageRuleContext) -> None:
        """Inspect a message-level context and emit findings.

        Args:
            ctx: The current message's context with old/new
                descriptors, pools, and path. Use ``ctx.emit(...)``
                to record findings.
        """
        ...


# ---------------------------------------------------------------------------
# Internal: build an emit closure for the engine to inject
# ---------------------------------------------------------------------------


def make_emit(
    rule_id: str,
    sink: list[Finding],
    *,
    old_descriptor: object | None = None,
    new_descriptor: object | None = None,
) -> EmitFn:
    """Build the ``_emit_fn`` closure handed to a plugin's context.

    The closure fills in ``rule_id`` and the descriptor references the
    user's plugin shouldn't have to remember, then appends the
    constructed ``Finding`` to ``sink``.

    Args:
        rule_id: The id under which the plugin was registered. Stored
            on every emitted ``Finding``.
        sink: Mutable list the closure appends to. The engine drains
            this after dispatch (via ``findings.extend(sink)``) so the
            sink can be a fresh per-call list.
        old_descriptor: Old-side descriptor reference (FieldDescriptor
            or Descriptor) to attach to every emitted finding. The
            plugin does not need to thread this through.
        new_descriptor: New-side descriptor reference, attached to
            every emitted finding.

    Returns:
        A keyword-only callable matching the ``EmitFn`` signature.
        Plugins should not call it directly; ``ctx.emit(...)`` wraps it.
    """

    def emit(
        *,
        path: FieldPath,
        severity: Severity,
        message: str,
        direction: Direction,
    ) -> None:
        sink.append(Finding(
            path=path,
            rule_id=rule_id,
            severity=severity,
            direction=direction,
            message=message,
            old_descriptor=old_descriptor,
            new_descriptor=new_descriptor,
        ))

    return emit


# ---------------------------------------------------------------------------
# Rule pack loading
# ---------------------------------------------------------------------------


def iter_rule_pack(module: ModuleType) -> list[tuple[str, FieldPlugin]]:
    """Return the ``RULES`` list from a rule-pack module.

    A rule pack is any Python module that defines a ``RULES`` attribute
    holding a sequence of ``(rule_id, plugin_fn)`` pairs.

    Args:
        module: An imported Python module (e.g., the result of
            ``importlib.import_module("myorg.proto_rules")``) that
            exposes a ``RULES`` attribute.

    Returns:
        A list of ``(rule_id, plugin_fn)`` tuples, validated for
        shape. ``SchemaChecker.load_rule_pack`` calls this then
        registers each pair via ``register_field_rule``.

    Raises:
        AttributeError: If ``module`` has no ``RULES`` attribute.
        TypeError: If any entry is not a 2-tuple of ``(str, callable)``.
    """
    rules = getattr(module, "RULES", None)
    if rules is None:
        raise AttributeError(
            f"rule pack '{module.__name__}' has no RULES attribute"
        )
    out: list[tuple[str, FieldPlugin]] = []
    for entry in rules:
        if (not isinstance(entry, tuple)) or len(entry) != 2:
            raise TypeError(
                f"rule pack '{module.__name__}' RULES entry is not a "
                f"(rule_id, fn) pair: {entry!r}"
            )
        rule_id, fn = entry
        if not isinstance(rule_id, str) or not callable(fn):
            raise TypeError(
                f"rule pack '{module.__name__}' RULES entry has wrong "
                f"types (expected (str, callable)): {entry!r}"
            )
        out.append((rule_id, fn))
    return out
