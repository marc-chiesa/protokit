"""Core protobuf message comparison engine.

Uses an iterative explicit stack (no recursion) with name-based field matching
for cross-descriptor-pool comparison and schema evolution detection.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any

from google.protobuf import descriptor as proto_descriptor
from google.protobuf.message import Message

from protokit._descriptors import (
    format_key,
    get_field_map,
    has_presence,
    is_map_field,
    is_repeated,
    label_name,
    type_name,
)
from protokit.message._presence import PresenceVerdict, presence_verdict
from protokit.message._selector import FieldSelector, SelectorSpec
from protokit.message._setmatch import greedy_multiset_pairing
from protokit.message.comparators import (
    FloatComparison,
    FloatConfig,
    MessageFieldComparison,
    compare_enum_cross_pool,
    compare_enum_same_pool,
    compare_float,
    compare_scalar,
    to_enum_value,
)
from protokit.message.model import (
    ChangeType,
    Difference,
    DiffResult,
    DuplicateKeyError,
    FieldHook,
    Diagnostic,
    FieldHookContext,
    FieldPath,
    HookStage,
    MessageHookContext,
    MessageValidateHook,
    MissingKeyError,
    PathSegment,
    _FieldHookState,
    _MessageHookState,
)

# Protobuf field type constants
FD = proto_descriptor.FieldDescriptor
TYPE_MESSAGE = FD.TYPE_MESSAGE
TYPE_ENUM = FD.TYPE_ENUM
TYPE_FLOAT = FD.TYPE_FLOAT
TYPE_DOUBLE = FD.TYPE_DOUBLE
TYPE_BYTES = FD.TYPE_BYTES
TYPE_BOOL = FD.TYPE_BOOL
TYPE_STRING = FD.TYPE_STRING
LABEL_REPEATED = FD.LABEL_REPEATED

def _hook_name(hook: object) -> str:
    """Best-effort display name for a hook in warning messages."""
    return getattr(hook, "__qualname__", None) or getattr(
        hook, "__name__", repr(hook),
    )


def _replace_bracket(path: FieldPath, bracket: str) -> FieldPath:
    """Return a new FieldPath with the last segment's bracket replaced.

    Args:
        path: The original field path.
        bracket: New bracket content for the last segment.

    Returns:
        A new FieldPath identical to ``path`` except the last segment
        carries the given bracket.
    """
    last = path.segments[-1]
    new_seg = PathSegment(name=last.name, bracket=bracket)
    return FieldPath(segments=path.segments[:-1] + (new_seg,))


# Type compatibility groups
_INTEGER_TYPES = frozenset({
    FD.TYPE_INT32, FD.TYPE_INT64, FD.TYPE_UINT32, FD.TYPE_UINT64,
    FD.TYPE_SINT32, FD.TYPE_SINT64, FD.TYPE_FIXED32, FD.TYPE_FIXED64,
    FD.TYPE_SFIXED32, FD.TYPE_SFIXED64,
})
_FLOAT_TYPES = frozenset({FD.TYPE_FLOAT, FD.TYPE_DOUBLE})

def _types_compatible(left_type: int, right_type: int) -> bool:
    """Check if two protobuf field types are compatible for value comparison.

    Args:
        left_type: Field type constant from the left descriptor.
        right_type: Field type constant from the right descriptor.

    Returns:
        True if the types are the same or belong to the same
        compatibility group (integer types, float types, or message types).
    """
    if left_type == right_type:
        return True
    if left_type in _INTEGER_TYPES and right_type in _INTEGER_TYPES:
        return True
    if left_type in _FLOAT_TYPES and right_type in _FLOAT_TYPES:
        return True
    return False


def _same_pool(left_msg: Message, right_msg: Message) -> bool:
    """Check if two messages are from the same descriptor pool.

    Args:
        left_msg: The left protobuf Message.
        right_msg: The right protobuf Message.

    Returns:
        True if both message descriptors reference the same pool object.
    """
    return left_msg.DESCRIPTOR.file.pool is right_msg.DESCRIPTOR.file.pool


# Strict float config for treat_as_set element equality (KTD-8): set-membership
# equality is always exact, never the per-field tolerance overlay. Hoisted to a
# module constant so the O(n*m) set-pairing loop does not allocate per pair.
_EXACT_FLOAT_CONFIG = FloatConfig(mode=FloatComparison.EXACT)


# ---------------------------------------------------------------------------
# Work item for the iterative stack
# ---------------------------------------------------------------------------

@dataclass
class _WorkItem:
    """A unit of comparison work for the stack-based engine.

    Attributes:
        force_emit: When True, a one-sided (added/removed) subtree is emitted
            in full even under partial scope. Set for subtrees produced by a
            ``treat_as_set`` comparison: partial deliberately does NOT descend
            into set fields (KTD-8 carve-out), so an actual-only set *message*
            element — pushed here by ``_compare_treat_as_set`` — must still be
            reported as ADDED. Default False; the ordinary partial gate applies.
    """

    left_msg: Message | None
    right_msg: Message | None
    path: FieldPath
    depth: int
    force_emit: bool = False


# ---------------------------------------------------------------------------
# MessageDifferencer
# ---------------------------------------------------------------------------


class MessageDifferencer:
    """Configurable protobuf message comparator.

    Uses an iterative explicit stack for unbounded depth support.
    Name-based field matching enables cross-descriptor-pool
    comparison and schema-evolution detection.

    Configure behavior by calling the instance methods
    (:meth:`ignore_fields`, :meth:`treat_as_map`,
    :meth:`set_float_comparison`, and the ``register_*_hook``
    methods) or by assigning to the public attributes below before
    calling :meth:`compare`.

    Thread safety: an instance is **not** thread-safe. :meth:`compare`
    stores descriptor pools on ``self`` during the call
    (``self._left_pool`` / ``self._right_pool``) so hooks can read
    them, and clears them in a ``finally``. Two concurrent
    :meth:`compare` calls on the same instance will race on those
    attributes and hooks may see the wrong pools. Use a distinct
    ``MessageDifferencer`` per thread, or serialize calls
    externally.

    Attributes:
        max_depth: Maximum recursion depth (``None`` for unlimited,
            the default). Subtrees below the limit are not compared
            and their paths appear in ``DiffResult.truncated_paths``.
        strict_schema: When True (default False), emit a ``Diagnostic``
            if two compared messages have different fully-qualified
            type names, even if their field shapes align.
    """

    def __init__(self) -> None:
        """Construct a differencer with default configuration.

        All configuration starts empty — no ignored fields, no
        ``treat_as_map`` entries, exact float comparison, unlimited
        depth, lenient schema mode, no hooks. Use the instance
        methods below to customize.
        """
        self._ignore_names: set[str] = set()  # bare names (global match)
        self._ignore_paths: list[FieldPath] = []  # parsed dotted paths
        self._ignore_fields_raw: list[str] = []  # raw selectors for conflict validation
        # Predicate-form ignore selectors (KTD-1/U2). Consulted at the same
        # selection gate (``_is_ignored``) as the string forms, but evaluated
        # against a FieldDescriptor + path rather than parsed from a string.
        self._ignore_selectors: list[FieldSelector] = []
        self._treat_as_map: dict[str, str] = {}  # field_name_or_path -> key_field_name
        self._treat_as_map_paths: list[tuple[FieldPath, str]] = []  # (parsed_path, key_name)
        # Keyless "set" comparison (KTD-8/U3): repeated fields marked here are
        # compared order-independently as multisets via greedy pairing, rather
        # than the default index pairing. Distinct from keyed ``treat_as_map``.
        self._treat_as_set_selectors: list[FieldSelector] = []
        # Partial / sub-shape scope (KTD-11/U4). When True, only fields present
        # on the EXPECTED (left) side are compared: extra fields on the actual
        # (right) side produce no ADDED difference, while left-only (REMOVED)
        # fields and value differences are STILL reported. Directional and
        # recursive; default off keeps full comparison behavior unchanged (R12).
        self._partial: bool = False
        # Field-presence comparison mode (KTD-7/U5). EQUIVALENT (default)
        # collapses a presence-bearing field set to its DEFAULT value with an
        # unset field; EQUAL distinguishes them. Observable only where presence
        # exists (proto2, proto3 ``optional``, oneof members, message fields);
        # a documented no-op for proto3 implicit-presence scalars. Default keeps
        # today's pinned output (set-to-non-default-vs-unset still reported).
        self._presence_mode: MessageFieldComparison = MessageFieldComparison.EQUIVALENT
        self._float_config = FloatConfig()
        # Per-field float tolerance overlays (KTD-6/U6). Each entry pairs a
        # FieldSelector with the FloatConfig to apply to the float/double fields
        # it selects. Consulted FIRST in the float-comparison path: the first
        # overlay whose selector matches ``(fd, path)`` supplies the config;
        # otherwise the global ``_float_config`` applies. This LAYERS over the
        # global setting rather than replacing it (R11) — an unscoped float field
        # keeps the global behavior unchanged. Empty list = fast path (global
        # only). Order is registration order; earlier overlays win ties.
        self._float_overlays: list[tuple[FieldSelector, FloatConfig]] = []
        self.max_depth: int | None = None
        self.strict_schema: bool = False
        # Phase 1.5 hook pipeline. Per-stage lists; empty = fast path.
        self._validate_hooks: list[FieldHook] = []
        self._compare_hooks: list[FieldHook] = []
        self._report_hooks: list[FieldHook] = []
        self._message_validate_hooks: list[MessageValidateHook] = []
        # Pools captured at ``compare()`` entry and cleared on exit.
        self._left_pool: Any = None
        self._right_pool: Any = None

    # ------------------------------------------------------------------
    # Phase 1.5 hook registration
    # ------------------------------------------------------------------

    def register_validate_hook(self, hook: FieldHook) -> None:
        """Register a VALIDATE-stage field hook.

        VALIDATE hooks fire before value comparison on every leaf
        evaluation — including presence-gated paths (both-unset,
        one-sided add/remove, repeated/map extras, map one-sided
        keys). Use for flagging constraint violations (e.g.
        ``validate.rules``) via ``ctx.warn()``.

        Firing granularity for aggregate fields: repeated and map
        fields fire hooks **per element/entry**, not once per
        field. ``ctx.left_value`` / ``ctx.right_value`` carry the
        individual scalar value; the field descriptor (with
        ``is_repeated=True``) is still in ``ctx.left_fd`` /
        ``ctx.right_fd``. Field-level constraints that span the
        whole list (e.g., "max_items") belong on a message-level
        hook registered against the parent message.

        Args:
            hook: Callable matching ``FieldHook``: takes a
                ``FieldHookContext``, returns ``None``. Should be
                synchronous. ``Exception`` subclasses raised by the
                hook are captured into ``DiffResult.warnings`` and
                comparison continues. ``BaseException`` (including
                ``KeyboardInterrupt`` and ``SystemExit``)
                propagates uncaught — by design, so users can still
                interrupt a long-running comparison.
        """
        self._validate_hooks.append(hook)

    def register_compare_hook(self, hook: FieldHook) -> None:
        """Register a COMPARE-stage field hook.

        COMPARE hooks can call ``ctx.override_equal()`` to force
        two leaf values to compare as equal, skipping the engine's
        default ``_values_equal``. Fires only when both sides have
        values — presence-gated paths (both-unset, one-sided
        add/remove, repeated/map extras, map one-sided keys) are
        structural and skip COMPARE.

        Args:
            hook: Callable matching ``FieldHook``. ``Exception``
                subclasses are captured into warnings and the
                engine falls back to the default comparison for
                that field. ``BaseException`` propagates uncaught.
        """
        self._compare_hooks.append(hook)

    def register_report_hook(self, hook: FieldHook) -> None:
        """Register a REPORT-stage field hook.

        REPORT hooks fire after a ``Difference`` is about to be
        emitted — MODIFIED (values differ), ADDED / REMOVED
        (presence change or repeated/map extra or one-sided map
        key). Use ``ctx.annotate(...)`` to attach strings that
        show up on ``Difference.annotations``. Multiple hooks can
        annotate one diff; strings accumulate in registration
        order.

        Args:
            hook: Callable matching ``FieldHook``. ``Exception``
                subclasses become warnings; the diff is still
                emitted with whatever annotations had already been
                collected before the hook raised. ``BaseException``
                propagates uncaught.
        """
        self._report_hooks.append(hook)

    def register_message_validate_hook(self, hook: MessageValidateHook) -> None:
        """Register a message-level VALIDATE hook.

        Fires once per visited message (including one-sided visits
        where one side of the subtree is absent) before field
        iteration. Message hooks can only ``warn()`` — they can't
        override comparison or annotate diffs, since those are
        per-field concerns.

        Args:
            hook: Callable matching ``MessageValidateHook``.
                Exceptions become warnings and comparison of the
                message continues.
        """
        self._message_validate_hooks.append(hook)

    # ------------------------------------------------------------------
    # Hook dispatch helpers
    # ------------------------------------------------------------------

    def _has_field_hooks(self) -> bool:
        """Whether any field-level hook is registered (any stage)."""
        return bool(
            self._validate_hooks or self._compare_hooks or self._report_hooks
        )

    def _fire_field_stage(
        self,
        stage: HookStage,
        hooks: list[FieldHook],
        ctx_state: _FieldHookState,
        ctx: FieldHookContext,
        warnings: list[Diagnostic],
        *,
        has_diff: bool = False,
    ) -> None:
        """Run every hook registered for ``stage`` on ``ctx``.

        Hooks are wrapped in ``try/except Exception`` — a raising
        hook becomes a ``Diagnostic`` and comparison continues.
        """
        if not hooks:
            ctx_state.reset_for_stage(stage, has_diff=has_diff)
            return
        ctx_state.reset_for_stage(stage, has_diff=has_diff)
        for hook in hooks:
            try:
                hook(ctx)
            except Exception as exc:
                warnings.append(Diagnostic(
                    path=str(ctx.path) if ctx.path else None,
                    message=(
                        f"hook {_hook_name(hook)!r} raised "
                        f"{type(exc).__name__} during {stage.value}: {exc}"
                    ),
                    level="error",
                ))

    def _drain_field_ctx_warnings(
        self,
        ctx_state: _FieldHookState,
        path: FieldPath,
        warnings: list[Diagnostic],
    ) -> None:
        """Move ``ctx.warn()`` / ``ctx.error()`` messages onto the caller's list.

        Both streams drain to the same diagnostics list on the
        result; ``level`` is what distinguishes them downstream
        (``DiffResult.warnings`` vs ``DiffResult.errors``).
        """
        if not ctx_state.warnings and not ctx_state.errors:
            return
        path_str = str(path) if path else None
        for msg in ctx_state.warnings:
            warnings.append(Diagnostic(path=path_str, message=msg))
        for msg in ctx_state.errors:
            warnings.append(Diagnostic(path=path_str, message=msg, level="error"))
        ctx_state.warnings = []
        ctx_state.errors = []

    def _run_validate_compare(
        self,
        ctx_state: _FieldHookState,
        ctx: FieldHookContext,
        left_val: Any, right_val: Any,
        left_fd: proto_descriptor.FieldDescriptor,
        right_fd: proto_descriptor.FieldDescriptor,
        same_pool: bool,
        warnings: list[Diagnostic],
        path: FieldPath,
    ) -> bool:
        """Run VALIDATE → COMPARE → ``_values_equal`` for a both-present leaf.

        Returns whether the two values should be treated as equal.
        Honors ``override_equal()`` calls from COMPARE hooks.
        """
        self._fire_field_stage(
            HookStage.VALIDATE, self._validate_hooks, ctx_state, ctx, warnings,
        )
        self._fire_field_stage(
            HookStage.COMPARE, self._compare_hooks, ctx_state, ctx, warnings,
        )
        if ctx_state.override_equal:
            return True
        return self._values_equal(
            left_val, right_val, left_fd, right_fd, same_pool, warnings, path,
        )

    def _emit_with_report(
        self,
        diff: Difference,
        ctx_state: _FieldHookState,
        ctx: FieldHookContext,
        diffs: list[Difference],
        warnings: list[Diagnostic],
        path: FieldPath,
    ) -> None:
        """Fire REPORT hooks, attach annotations, append to ``diffs``."""
        self._fire_field_stage(
            HookStage.REPORT, self._report_hooks, ctx_state, ctx, warnings,
            has_diff=True,
        )
        if ctx_state.annotations:
            diff = dataclasses.replace(
                diff, annotations=tuple(ctx_state.annotations),
            )
        diffs.append(diff)
        self._drain_field_ctx_warnings(ctx_state, path, warnings)

    def _fire_message_validate(
        self,
        item: _WorkItem,
        warnings: list[Diagnostic],
    ) -> None:
        """Fire message-level VALIDATE hooks for the current stack item."""
        if not self._message_validate_hooks:
            return
        state = _MessageHookState()
        ctx = MessageHookContext(
            path=item.path,
            left_msg=item.left_msg,
            right_msg=item.right_msg,
            left_pool=self._left_pool,
            right_pool=self._right_pool,
            _state=state,
        )
        for hook in self._message_validate_hooks:
            try:
                hook(ctx)
            except Exception as exc:
                warnings.append(Diagnostic(
                    path=str(item.path) if item.path else None,
                    message=(
                        f"hook {_hook_name(hook)!r} raised "
                        f"{type(exc).__name__} during message VALIDATE: {exc}"
                    ),
                    level="error",
                ))
        if state.warnings or state.errors:
            path_str = str(item.path) if item.path else None
            for msg in state.warnings:
                warnings.append(Diagnostic(path=path_str, message=msg))
            for msg in state.errors:
                warnings.append(Diagnostic(
                    path=path_str, message=msg, level="error",
                ))

    def ignore_fields(self, *selectors: SelectorSpec) -> None:
        """Add field selectors to the ignore list.

        Accepts three forms, freely mixed in one call:

        * **Bare name** (``"timestamp"``) — ignores that field everywhere.
        * **Dotted path** (``"header.timestamp"``) — ignores only that
          specific location (bracket-blind, exact-length match, so
          ``"items.name"`` also matches ``"items[0].name"``).
        * **Predicate / FieldSelector** — a
          ``(FieldDescriptor, FieldPath) -> bool`` callable (or a
          pre-built :class:`FieldSelector`) consulted per field at the same
          selection gate as the string forms. The predicate receives the
          field's descriptor and concrete path as explicit arguments
          (KTD-10); any exception it raises propagates unchanged — a buggy
          predicate is an author error, not an engine fault, and is NOT
          captured into diagnostics.

        Ignore applies symmetrically: an ignored field is suppressed whether
        it differs, is added (present only on the right/actual side), or is
        removed (present only on the left/expected side), because the gate is
        consulted both pre-dispatch and inside ``_emit_all_fields``.

        Conflict validation with ``treat_as_map`` is enforced at registration
        for the string forms only. A predicate-form ignore CANNOT be
        conflict-checked at registration — the callable is opaque and no
        descriptor is in hand — so no such check is attempted for it. The
        compare-time behavior when a predicate ignores a field that is also
        ``treat_as_map``-keyed is defined as **ignore wins**: the field is
        simply not visited, so its map key is never consulted. This is
        intentional and silent (there is no cheap, reliable overlap signal at
        compare time for an opaque predicate).

        Args:
            *selectors: One or more ignore selectors (bare name, dotted path,
                predicate, or :class:`FieldSelector`), in any mix.

        Raises:
            ValueError: If a *string* selector uses bracket syntax, or
                conflicts with a ``treat_as_map`` configuration (e.g.
                ignoring a map key field). Predicate-form selectors are not
                conflict-checked at registration (see above).
        """
        # Partition string selectors (existing path) from predicate/selector
        # forms (new path). Strings keep byte-identical behavior, including
        # conflict validation; the selector forms route to _ignore_selectors.
        string_selectors: list[str] = []
        selector_forms: list[FieldSelector] = []
        for spec in selectors:
            if isinstance(spec, str):
                string_selectors.append(spec)
            else:
                # FieldSelector or (FieldDescriptor, FieldPath) -> bool callable.
                # FieldSelector.of returns a FieldSelector as-is and wraps a
                # callable; it rejects anything else with a clear TypeError.
                selector_forms.append(FieldSelector.of(spec))

        # Validate all string selectors before mutating state
        for sel in string_selectors:
            if "[" in sel:
                raise ValueError(
                    f"Bracket syntax is not supported in ignore selectors: '{sel}'. "
                    "Use bare field names or dotted paths (e.g. 'field' or 'parent.field')."
                )
            if sel in self._treat_as_map:
                raise ValueError(
                    f"Cannot ignore field '{sel}' that is configured as treat_as_map"
                )

        # Check for conflicts with treat_as_map key fields
        for map_sel, key_name in self._treat_as_map.items():
            for ign in string_selectors:
                # Bare name that matches the key
                if "." not in ign and ign == key_name:
                    raise ValueError(
                        f"Cannot ignore '{ign}' globally because it's the key field "
                        f"for treat_as_map('{map_sel}', key='{key_name}')"
                    )
                # Path-scoped that targets the key inside the map field
                if "." in ign and ign == f"{map_sel}.{key_name}":
                    raise ValueError(
                        f"Cannot ignore '{ign}' because it's the key field "
                        f"for treat_as_map('{map_sel}', key='{key_name}')"
                    )

        # All validation passed — safe to mutate
        self._ignore_fields_raw.extend(string_selectors)
        for sel in string_selectors:
            if "." in sel:
                self._ignore_paths.append(FieldPath.parse(sel))
            else:
                self._ignore_names.add(sel)
        self._ignore_selectors.extend(selector_forms)

    def treat_as_map(self, field_selector: str, *, key: str) -> None:
        """Configure a repeated message field for key-based matching.

        Instead of pairing repeated-field elements by index, the
        engine will match elements by the value of the given key
        sub-field. Paths for matched elements use the
        ``items[key="abc"].field`` form. Elements with duplicate or
        missing keys raise ``DuplicateKeyError`` / ``MissingKeyError``.

        Args:
            field_selector: Bare field name (``"items"``) for a
                global match or dotted path (``"parent.items"``) for
                a scoped match. The field must be a repeated message
                field on both sides.
            key: Name of the scalar sub-field to use as the map key.
                Must be a scalar type (string, int, bool, enum).

        Raises:
            ValueError: If ``field_selector`` or ``key`` conflicts
                with an existing ignore configuration, or if the
                same field is already configured with a different
                key.
        """
        # Check for conflicts with already-configured ignore fields
        for ign in self._ignore_fields_raw:
            # The field itself is ignored
            if ign == field_selector:
                raise ValueError(
                    f"Cannot treat_as_map field '{field_selector}' that is "
                    f"already ignored"
                )
            # Bare name that matches the key
            if "." not in ign and ign == key:
                raise ValueError(
                    f"Cannot use key '{key}' for treat_as_map('{field_selector}') "
                    f"because '{ign}' is globally ignored"
                )
            # Path-scoped that targets the key inside the map field
            if "." in ign and ign == f"{field_selector}.{key}":
                raise ValueError(
                    f"Cannot use key '{key}' for treat_as_map('{field_selector}') "
                    f"because '{ign}' is ignored"
                )

        # Reverse conflict: the field cannot already be treat_as_set (keyless).
        # Only path-form set selectors are checkable here (predicates opaque).
        map_path = FieldPath.parse(field_selector)
        for set_sel in self._treat_as_set_selectors:
            set_path = set_sel.path
            if set_path is not None and set_path.matches_selector(map_path):
                raise ValueError(
                    f"Cannot treat_as_map field '{field_selector}' that is "
                    f"already configured as treat_as_set"
                )

        # Re-registration: the dict is last-wins but the path list is
        # append-only and first-wins at lookup, so silently overwriting would
        # leave the two stores disagreeing about the key actually in force
        # (and the conflict checks above read only the dict). Reject the
        # conflict; an identical repeat is a harmless no-op.
        existing_key = self._treat_as_map.get(field_selector)
        if existing_key is not None:
            if existing_key != key:
                raise ValueError(
                    f"Cannot treat_as_map field '{field_selector}' with key "
                    f"'{key}': already configured with key '{existing_key}'"
                )
            return

        self._treat_as_map[field_selector] = key
        if "." in field_selector:
            self._treat_as_map_paths.append((FieldPath.parse(field_selector), key))

    def treat_as_set(self, selector: SelectorSpec) -> None:
        """Configure a repeated field for keyless, order-independent matching.

        Unlike :meth:`treat_as_map` (which pairs elements by a key sub-field),
        set comparison has NO key: elements are paired as a multiset via greedy
        first-fit equality (KTD-8). Two repeated fields holding the same
        elements in a different order compare equal; leftovers are reported as
        REMOVED (expected-side) and ADDED (actual-side) for the unmatched
        elements, using the same element ``Difference`` shape as the default
        index path.

        Applies to scalar/enum and message repeated fields. Set-membership
        equality is STRICT exact equality — it deliberately does NOT apply
        float tolerance or other per-element policies inside element
        comparison, so equality stays a true equivalence relation and the
        partition is order-independent. Cost is ``O(n * m)`` element-equality
        evaluations; for message elements each is a full sub-comparison, so it
        is intended for test-sized repeated fields.

        A selector that matches a non-repeated field silently has no effect: set
        comparison is consulted only at the repeated-field site, so a selector
        aimed at a singular field is a no-op rather than an error (consistent
        with the opaque-predicate ignore path).

        Args:
            selector: A bare field name (``"items"``), a dotted path
                (``"parent.items"``), a ``(FieldDescriptor, FieldPath) -> bool``
                predicate, or a pre-built :class:`FieldSelector`. The same
                selection model every selective policy uses (R9).

        Raises:
            TypeError: If ``selector`` is not a str, callable, or
                :class:`FieldSelector` (propagated from
                :meth:`FieldSelector.of`).
            ValueError: If ``selector`` is a *string/path* form that is also
                configured as ``treat_as_map`` (a field cannot be both keyed
                and keyless). Predicate-form selectors are opaque and cannot be
                conflict-checked at registration (mirroring predicate ignore).
        """
        field_selector = FieldSelector.of(selector)

        # Conflict validation: a field cannot be both treat_as_map (keyed) and
        # treat_as_set (keyless). Only checkable for path/string forms — a
        # predicate is opaque with no descriptor in hand at registration.
        sel_path = field_selector.path
        if sel_path is not None:
            for map_sel in self._treat_as_map:
                if FieldPath.parse(map_sel).matches_selector(sel_path):
                    raise ValueError(
                        f"Cannot treat_as_set field '{sel_path}' that is "
                        f"already configured as treat_as_map('{map_sel}')"
                    )

        self._treat_as_set_selectors.append(field_selector)

    def set_partial(self, partial: bool = True) -> None:
        """Enable (or disable) partial / sub-shape comparison (R5/U4).

        Partial matching is **directional**: ``compare(left, right)`` treats
        ``left`` as the expected side and ``right`` as the actual side. With
        partial enabled, only fields present on the EXPECTED (left) side
        participate in comparison:

        * A field (or whole sub-message) present ONLY on the actual (right)
          side — an ADDED difference in full mode — is **suppressed**: extra
          fields on actual are not differences.
        * A field present on the expected (left) side but MISSING on actual —
          a REMOVED difference — is **still reported**. Partial does not relax
          the requirement that expected fields be present.
        * A field present on both sides whose values DIFFER is **still
          reported** (a value difference).
        * Within a repeated or map field that IS present on the expected side,
          extra trailing elements (index-paired repeated) and extra keys (map)
          present only on actual are likewise **suppressed** — actual may be a
          superset of the expected collection. A missing expected element / key
          still reports REMOVED, and a paired element whose value differs still
          reports. Order still matters for the index-paired default; use
          :meth:`treat_as_set` for order-independent membership.

        The rule recurses: within a nested message present on the expected
        side, the same expected-defines-the-shape rule applies to its fields,
        so extra nested actual fields are likewise ignored while missing or
        differing expected nested fields still report.

        **``treat_as_set`` carve-out (KTD-8):** partial does NOT descend into a
        repeated field marked :meth:`treat_as_set`. Set-element equality stays
        STRICT exact equality so the multiset partition remains an equivalence
        relation; so — unlike the index-paired collection case above — a set
        element present only on the actual side IS still reported even under
        partial. Partial relaxes the *field-shape*, never set membership.

        Default is full comparison (``partial=False``); the default behavior is
        unchanged and every existing comparison is unaffected (R12).

        Args:
            partial: ``True`` to enable partial / sub-shape scope, ``False`` to
                restore full comparison. Defaults to ``True`` so
                ``set_partial()`` reads as "turn partial on".
        """
        self._partial = partial

    @staticmethod
    def _present_on_expected(
        msg: Message,
        left_fd: proto_descriptor.FieldDescriptor,
        default_msg: Message | None,
    ) -> bool:
        """Whether ``left_fd`` is "present" on the expected (left) side (U4).

        Partial / sub-shape matching treats the expected message's set fields
        as the shape to check. Presence here means:

        - repeated / map fields: non-empty on the expected side;
        - presence-bearing singular fields (messages, proto3 ``optional``,
          oneof members, all proto2 fields): ``HasField`` is true;
        - proto3 implicit-presence scalars/enums: a non-default value — they
          carry no presence bit, so a defaulted expected field is
          indistinguishable from unset and is treated as "not in the sub-shape"
          (the documented proto3 limitation). Without this, such a field is
          both-present and would surface as MODIFIED, defeating partial.

        ``default_msg`` is a once-per-message default instance used to read each
        implicit field's zero value; built lazily if not supplied.
        """
        if left_fd.label == left_fd.LABEL_REPEATED:  # repeated + map
            return len(getattr(msg, left_fd.name)) > 0
        if left_fd.has_presence:
            return msg.HasField(left_fd.name)
        if default_msg is None:
            default_msg = type(msg)()
        return getattr(msg, left_fd.name) != getattr(default_msg, left_fd.name)

    def set_message_field_comparison(
        self, mode: MessageFieldComparison
    ) -> None:
        """Configure field-presence comparison semantics (KTD-7/U5).

        Mirrors C++ ``MessageDifferencer::set_message_field_comparison``.

        Controls how a singular field's *presence* (set vs unset) is compared
        when one side has the field set and the other does not:

        * :attr:`MessageFieldComparison.EQUIVALENT` (the default) treats a
          field set to its **default value** as equal to an unset field — the
          "set-to-default ≈ unset" collapse. A field set to a *non-default*
          value vs unset is still reported as a presence difference (today's
          pinned behavior, unchanged).
        * :attr:`MessageFieldComparison.EQUAL` (opt-in) reports a presence
          difference whenever a presence-bearing field is set on one side
          (even to its default value) and unset on the other.

        EQUAL is observable only where presence exists — proto2 fields, proto3
        ``optional`` fields, oneof members, and singular message fields. It is a
        documented NO-OP for proto3 implicit-presence scalars, which carry no
        presence bit and so cannot distinguish a default value from unset.

        Args:
            mode: ``MessageFieldComparison.EQUIVALENT`` (default) or
                ``MessageFieldComparison.EQUAL``.
        """
        self._presence_mode = mode

    def set_float_comparison(
        self,
        mode: FloatComparison,
        fraction: float = 1e-6,
        margin: float = 1e-9,
        *,
        selector: SelectorSpec | None = None,
    ) -> None:
        """Configure how float (and double) fields are compared.

        Default is exact IEEE 754 comparison.

        Two layered scopes are supported:

        * **Global** (``selector=None``, the default): sets the baseline
            ``FloatConfig`` applied to every float/double field that no overlay
            selects. This is the original behavior and is unchanged.
        * **Per-field overlay** (``selector=...``): registers a
            ``(FieldSelector, FloatConfig)`` overlay applied ONLY to the
            float/double fields the selector matches (KTD-6/U6). Overlays
            LAYER over the global setting (R11) — they never replace it. During
            comparison the overlays are consulted first (in registration order);
            the first whose selector matches the field supplies the config, and
            any unmatched float field falls back to the global ``FloatConfig``.
            Both ``fraction`` and ``margin`` are honored per overlay. Call again
            with a different ``selector`` to register additional overlays.

        The selector resolves over map/repeated float element values too: a
        path-form selector (e.g. ``"ratios"``) matches via the element path,
        and a descriptor-predicate selector receives the *container* field
        descriptor (not the synthetic ``MapEntry.value`` descriptor) so it sees
        the user's field name.

        An overlay ``selector`` that matches a non-float/double field silently
        has no effect: float configs are consulted only at float/double
        comparison sites, so a selector aimed at a wrong-typed field is a no-op
        rather than an error (consistent with the opaque-predicate ignore path).

        Args:
            mode: ``FloatComparison.EXACT`` for bit-identical
                comparison (NaN != NaN, ±0 distinguished) or
                ``FloatComparison.APPROXIMATE`` for tolerance-based
                comparison using ``fraction`` and ``margin``.
            fraction: Relative tolerance for approximate mode:
                values are equal if ``|a - b| <= fraction * max(|a|, |b|)``.
                Defaults to ``1e-6``. Ignored in EXACT mode.
            margin: Absolute tolerance for approximate mode: values
                are equal if ``|a - b| <= margin``. Combined with
                ``fraction`` as a logical OR. Defaults to ``1e-9``.
                Ignored in EXACT mode.
            selector: When provided, a bare name / dotted path string, a
                ``(FieldDescriptor, FieldPath) -> bool`` predicate, or a
                :class:`FieldSelector` scoping this ``mode``/``fraction``/
                ``margin`` to the matching float fields as an overlay over the
                global setting. When ``None`` (default), the global float config
                is set instead.
        """
        config = FloatConfig(mode=mode, fraction=fraction, margin=margin)
        if selector is None:
            self._float_config = config
            return
        self._float_overlays.append((FieldSelector.of(selector), config))

    def compare(self, left: Message, right: Message) -> DiffResult:
        """Compare two protobuf messages and return a structured diff.

        The traversal uses an explicit stack, so recursion depth is
        bounded by ``max_depth`` (unlimited by default), not by the
        Python call stack. Name-based field matching lets ``left``
        and ``right`` come from different descriptor pools.

        Args:
            left: The left-side protobuf ``Message``. Treated as the
                "old" or "expected" side for directional semantics
                like ``ChangeType.REMOVED``.
            right: The right-side protobuf ``Message``. Treated as
                the "new" or "actual" side.

        Returns:
            A ``DiffResult`` with every detected ``Difference``,
            any ``Diagnostic`` diagnostics (schema drift, cardinality
            change, ``treat_as_map`` fallbacks), and the set of
            paths where ``max_depth`` cut off traversal. Differences
            are sorted by path for deterministic output.

        Raises:
            DuplicateKeyError: A ``treat_as_map``-configured field
                had duplicate keys in one side's elements.
            MissingKeyError: A ``treat_as_map``-configured field had
                an element with the key sub-field unset.
        """
        differences: list[Difference] = []
        warnings: list[Diagnostic] = []
        truncated_paths: list[FieldPath] = []
        same_pool = _same_pool(left, right)

        # Capture pools for the duration of this call so hooks can
        # use them for custom-option lookups via
        # ``protokit.options.get_option_value``. Cleared in the
        # ``finally`` below so the differ is safe to re-use.
        self._left_pool = left.DESCRIPTOR.file.pool
        self._right_pool = right.DESCRIPTOR.file.pool

        stack: list[_WorkItem] = [_WorkItem(left, right, FieldPath(segments=()), 0)]

        # Strict-schema type-name findings already emitted on this call, so the
        # per-field declared check and the per-work-item instance check never
        # say the same thing twice. See ``_check_message_type_names``.
        reported_type_names: set[tuple[tuple[str, ...], str, str]] = set()

        try:
            while stack:
                item = stack.pop()

                # Max depth check
                if self.max_depth is not None and item.depth > self.max_depth:
                    truncated_paths.append(item.path)
                    warnings.append(Diagnostic(
                        path=str(item.path) if item.path else None,
                        message=f"comparison truncated at depth {self.max_depth}; "
                                "differences below this path are not reported",
                    ))
                    continue

                if item.left_msg is None and item.right_msg is None:
                    continue

                # Message-level VALIDATE fires for every message visit —
                # including one-sided (added/removed) subtrees. Zero-hooks
                # fast path inside the helper.
                self._fire_message_validate(item, warnings)

                # Unset -> set (or vice versa) for message fields
                if item.left_msg is None and item.right_msg is not None:
                    # Direction-conditioned partial gate (U4): a whole
                    # sub-message present only on the actual (right) side is an
                    # ADDED subtree — suppress it under partial. The matching
                    # REMOVED branch below is NOT suppressed, so an
                    # expected-only subtree still reports fully (R5). Catches
                    # actual-only subtrees pushed by ``_compare_message_field``
                    # / ``_emit_one_sided`` before this separate recursive walk.
                    # ``force_emit`` bypasses the gate for set-element subtrees:
                    # partial does not descend into ``treat_as_set`` fields
                    # (KTD-8 carve-out), so those still report.
                    if not self._partial or item.force_emit:
                        self._emit_all_fields(item.right_msg, item.path, ChangeType.ADDED,
                                              differences, is_new=True, depth=item.depth,
                                              warnings=warnings, truncated_paths=truncated_paths)
                    continue
                if item.left_msg is not None and item.right_msg is None:
                    self._emit_all_fields(item.left_msg, item.path, ChangeType.REMOVED,
                                          differences, is_new=False, depth=item.depth,
                                          warnings=warnings, truncated_paths=truncated_paths)
                    continue

                assert item.left_msg is not None and item.right_msg is not None

                # Strict schema, checked per work item and not only per field:
                # the ROOT pair never reaches the per-field loop below (it has
                # no field descriptor), so two entirely different root types
                # with aligned field shapes used to compare completely clean.
                # It also catches drift the declared check structurally cannot
                # see — a map whose VALUE message type changed, where both
                # sides' declared field type is the identically named synthetic
                # MapEntry.
                if self.strict_schema:
                    self._check_message_type_names(
                        item.left_msg.DESCRIPTOR.full_name,
                        item.right_msg.DESCRIPTOR.full_name,
                        item.path, warnings, reported_type_names,
                    )

                left_fields = get_field_map(item.left_msg.DESCRIPTOR)
                right_fields = get_field_map(item.right_msg.DESCRIPTOR)

                all_names = left_fields.keys() | right_fields.keys()

                # Sort by left-side field number for deterministic ordering
                def _sort_key(name: str) -> tuple[int, int, str]:
                    if name in left_fields:
                        return (0, left_fields[name].number, name)
                    return (1, right_fields[name].number, name)

                # Process in reverse order since we're using a stack (LIFO)
                sorted_names = sorted(all_names, key=_sort_key, reverse=True)

                # Partial mode: the expected (left) message defines the
                # sub-shape; build its default once so implicit-presence scalars
                # can be tested by non-default value.
                left_default = type(item.left_msg)() if self._partial else None

                for field_name in sorted_names:
                    # Fast path: check bare-name ignore before allocating FieldPath
                    if field_name in self._ignore_names:
                        continue
                    field_path = item.path.child(field_name)

                    left_fd = left_fields.get(field_name)
                    right_fd = right_fields.get(field_name)

                    # Check path-scoped and predicate ignores. Pass a descriptor
                    # (expected/left side preferred, falling back to the
                    # right-only side) so predicate-form selectors can evaluate;
                    # this keeps ignore symmetric across modified/added/removed.
                    if (self._ignore_paths or self._ignore_selectors) and (
                        self._is_ignored(
                            field_name, field_path, left_fd or right_fd
                        )
                    ):
                        continue

                    # Field only on one side
                    if left_fd is None and right_fd is not None:
                        # Partial visit gate (U4): an actual-only (right-only)
                        # field is ADDED — skip it under partial so extra
                        # fields on actual are not differences. The right-only
                        # field is by definition not present on expected, so
                        # the partial gate always skips it.
                        if self._partial:
                            continue
                        self._emit_one_sided(
                            item.right_msg, right_fd, field_path,
                            differences, stack, item.depth, is_new=True,
                            warnings=warnings,
                        )
                        continue
                    if left_fd is not None and right_fd is None:
                        # Left-only (expected-only) field is REMOVED — always
                        # reported, even under partial (an expected-present
                        # field is always in the sub-shape); R5.
                        self._emit_one_sided(
                            item.left_msg, left_fd, field_path,
                            differences, stack, item.depth, is_new=False,
                            warnings=warnings,
                        )
                        continue

                    assert left_fd is not None and right_fd is not None

                    # Partial visit gate (U4) for both-present fields: under
                    # partial, only fields present on the expected (left) side
                    # are in the sub-shape. This catches proto3 implicit-presence
                    # scalars (default on expected, set on actual) that are
                    # both-present and would otherwise surface as MODIFIED; a
                    # treat_as_set field non-empty on expected is still compared
                    # strictly (KTD-8 carve-out, since it counts as present).
                    if self._partial and not self._present_on_expected(
                        item.left_msg, left_fd, left_default,
                    ):
                        continue

                    # Schema evolution checks
                    self._check_schema_evolution(
                        left_fd, right_fd, field_path, differences, warnings,
                        reported_type_names,
                    )

                    # Cardinality change -> no value comparison
                    if is_repeated(left_fd) != is_repeated(right_fd):
                        continue
                    left_is_map = is_map_field(left_fd)
                    right_is_map = is_map_field(right_fd)
                    if left_is_map != right_is_map:
                        left_kind = "map" if left_is_map else "repeated"
                        right_kind = "map" if right_is_map else "repeated"
                        warnings.append(Diagnostic(
                            path=str(field_path),
                            message=f"field changed from {left_kind} to {right_kind}; "
                                    "values not compared",
                        ))
                        continue

                    # Type compatibility
                    if not _types_compatible(left_fd.type, right_fd.type):
                        continue

                    # Compare values based on field type
                    if left_is_map:
                        self._compare_map(
                            item.left_msg, item.right_msg, left_fd, right_fd,
                            field_path, differences, stack, item.depth,
                            warnings, same_pool,
                        )
                    elif is_repeated(left_fd):
                        self._compare_repeated(
                            item.left_msg, item.right_msg, left_fd, right_fd,
                            field_path, differences, stack, item.depth,
                            warnings, same_pool,
                        )
                    elif left_fd.type == TYPE_MESSAGE:
                        self._compare_message_field(
                            item.left_msg, item.right_msg, left_fd, right_fd,
                            field_path, stack, item.depth, differences,
                            warnings, same_pool,
                        )
                    else:
                        self._compare_leaf(
                            item.left_msg, item.right_msg, left_fd, right_fd,
                            field_path, differences, warnings, same_pool,
                        )
        finally:
            # Clear pool refs so the differ is safe to re-use.
            self._left_pool = None
            self._right_pool = None

        # Sort results by path for deterministic output
        differences.sort(key=lambda d: str(d.path))

        return DiffResult(
            differences=tuple(differences),
            diagnostics=tuple(warnings),
            truncated_paths=tuple(truncated_paths),
        )

    # --- Internal methods ---

    def _is_ignored(
        self,
        field_name: str,
        field_path: FieldPath,
        fd: proto_descriptor.FieldDescriptor | None = None,
    ) -> bool:
        """Check if a field should be ignored.

        Consults the three ignore forms in cheapest-first order: the bare-name
        set (fast path), the parsed dotted paths, then the predicate-form
        :class:`FieldSelector` list. Predicate selectors need the field's
        descriptor, so callers thread ``fd`` through; if a predicate-form
        selector is configured but ``fd`` is ``None`` (no descriptor available
        at the call site), the predicate is conservatively not consulted and
        only the string forms apply.

        A predicate raising during this check PROPAGATES — it is an author bug,
        not an engine fault, so it is deliberately not captured into
        diagnostics (KTD-10 / SWI-3).

        Args:
            field_name: The bare field name.
            field_path: The fully qualified field path.
            fd: The field's descriptor, required to evaluate predicate-form
                selectors. ``None`` when no descriptor is available at the
                call site (string-form ignore still applies).

        Returns:
            True if the field matches any configured ignore selector.
        """
        if field_name in self._ignore_names:
            return True
        for sel_path in self._ignore_paths:
            # Bracket-blind, exact-length segment-name match.
            # This ensures "items.name" matches "items[0].name".
            if sel_path.matches_selector(field_path):
                return True
        if self._ignore_selectors and fd is not None:
            for selector in self._ignore_selectors:
                # Predicate exceptions propagate (author bug, not engine fault).
                if selector.matches(fd, field_path):
                    return True
        return False

    def _check_schema_evolution(
        self,
        left_fd: proto_descriptor.FieldDescriptor,
        right_fd: proto_descriptor.FieldDescriptor,
        path: FieldPath,
        diffs: list[Difference],
        warnings: list[Diagnostic],
        reported_type_names: set[tuple[tuple[str, ...], str, str]],
    ) -> None:
        """Check for schema evolution between two field descriptors.

        Detects field number changes, type changes, and cardinality changes
        between ``left_fd`` and ``right_fd``, appending any findings to
        ``diffs`` and ``warnings``.

        Args:
            left_fd: Field descriptor from the left message schema.
            right_fd: Field descriptor from the right message schema.
            path: The current field path for reporting.
            diffs: Accumulator list for Difference objects.
            warnings: Accumulator list for Diagnostic objects.
            reported_type_names: Per-``compare`` dedupe state shared with the
                per-work-item type-name check (see
                ``_check_message_type_names``).
        """
        # Field number change
        if left_fd.number != right_fd.number:
            diffs.append(Difference(
                path=path,
                change_type=ChangeType.FIELD_NUMBER_CHANGED,
                field_type=type_name(left_fd.type),
                left_field_number=left_fd.number,
                right_field_number=right_fd.number,
            ))

        # Type change (skip for message->message)
        if left_fd.type != right_fd.type:
            if not (left_fd.type == TYPE_MESSAGE and right_fd.type == TYPE_MESSAGE):
                diffs.append(Difference(
                    path=path,
                    change_type=ChangeType.TYPE_CHANGED,
                    left_type=type_name(left_fd.type),
                    right_type=type_name(right_fd.type),
                ))

        # Cardinality change
        if is_repeated(left_fd) != is_repeated(right_fd):
            diffs.append(Difference(
                path=path,
                change_type=ChangeType.CARDINALITY_CHANGED,
                field_type=type_name(left_fd.type),
                left_label=label_name(left_fd),
                right_label=label_name(right_fd),
            ))

        # Strict schema: message type name mismatch warning. Reported from the
        # DECLARED types so drift is still caught when the sub-message is unset
        # on both sides — the recursive walk only ever sees populated types.
        if (
            self.strict_schema
            and left_fd.type == TYPE_MESSAGE
            and right_fd.type == TYPE_MESSAGE
        ):
            self._check_message_type_names(
                left_fd.message_type.full_name,
                right_fd.message_type.full_name,
                path, warnings, reported_type_names,
            )

    def _check_message_type_names(
        self,
        left_name: str,
        right_name: str,
        path: FieldPath,
        warnings: list[Diagnostic],
        reported: set[tuple[tuple[str, ...], str, str]],
    ) -> None:
        """Emit at most one strict-schema type-name diagnostic per finding.

        Both the per-field declared check and the per-work-item instance check
        funnel through here so a single drift is announced once: a message
        field's declared drift is reported at the field path, and the work item
        later popped for that same sub-message would otherwise repeat it. The
        dedupe key ignores bracket segments, which also collapses a repeated
        field's ``items[0]`` / ``items[1]`` elements — one declared drift, one
        diagnostic — onto the ``items`` path the declared check already used.

        Args:
            left_name: Fully qualified type name on the left/expected side.
            right_name: Fully qualified type name on the right/actual side.
            path: Path to report the finding at (empty for the root pair).
            warnings: Accumulator list for Diagnostic objects.
            reported: Per-``compare`` set of findings already emitted.
        """
        if left_name == right_name:
            return
        key = (tuple(seg.name for seg in path.segments), left_name, right_name)
        if key in reported:
            return
        reported.add(key)
        warnings.append(Diagnostic(
            path=str(path) if path else None,
            message=f"message type name changed: {left_name} -> {right_name}",
        ))

    def _compare_leaf(
        self,
        left_msg: Message,
        right_msg: Message,
        left_fd: proto_descriptor.FieldDescriptor,
        right_fd: proto_descriptor.FieldDescriptor,
        path: FieldPath,
        diffs: list[Difference],
        warnings: list[Diagnostic],
        same_pool: bool,
    ) -> None:
        """Compare a leaf (scalar/enum/bytes/float) field.

        Handles presence semantics for proto2/proto3 optional fields
        and dispatches hooks around value comparison when any are
        registered. The zero-hooks path is an inline fast-path that
        calls ``_values_equal`` directly.

        Args:
            left_msg: The left parent message.
            right_msg: The right parent message.
            left_fd: Field descriptor from the left schema.
            right_fd: Field descriptor from the right schema.
            path: The current field path for reporting.
            diffs: Accumulator list for Difference objects.
            warnings: Accumulator list for Diagnostic objects.
            same_pool: True if both messages share a descriptor pool.
        """
        left_val = getattr(left_msg, left_fd.name)
        right_val = getattr(right_msg, right_fd.name)

        # Presence check for proto2/proto3 optional
        left_has = has_presence(left_fd)
        right_has = has_presence(right_fd)

        left_present = True
        right_present = True
        if left_has and right_has:
            left_present = left_msg.HasField(left_fd.name)
            right_present = right_msg.HasField(right_fd.name)

        has_field_hooks = self._has_field_hooks()

        # Fast path: no hooks → original behavior inlined.
        if not has_field_hooks:
            if left_has and right_has:
                # Route the one-sided presence delta through the EQUAL/
                # EQUIVALENT decision (U5). EQUIVALENT collapses a
                # set-to-DEFAULT-vs-unset delta (COLLAPSE); EQUAL always
                # reports it. A set-to-non-default-vs-unset delta reports in
                # BOTH modes (today's pinned behavior). EQUAL_PRESENCE (both
                # set or both unset) falls through to value comparison.
                # Reuse the presence already read above (left_present/
                # right_present) rather than letting presence_verdict recompute
                # the HasField pair — same verdict, half the presence reads.
                verdict = presence_verdict(
                    left_msg, right_msg, left_fd, right_fd,
                    equal_mode=self._presence_mode == MessageFieldComparison.EQUAL,
                    left_set=left_present, right_set=right_present,
                )
                if verdict is PresenceVerdict.COLLAPSE:
                    return
                if verdict is PresenceVerdict.ADDED:
                    diffs.append(Difference(
                        path=path,
                        change_type=ChangeType.ADDED,
                        right_value=self._wrap_value(right_val, right_fd),
                        field_type=type_name(right_fd.type),
                    ))
                    return
                if verdict is PresenceVerdict.REMOVED:
                    diffs.append(Difference(
                        path=path,
                        change_type=ChangeType.REMOVED,
                        left_value=self._wrap_value(left_val, left_fd),
                        field_type=type_name(left_fd.type),
                    ))
                    return
            equal = self._values_equal(
                left_val, right_val, left_fd, right_fd,
                same_pool, warnings, path,
            )
            if not equal:
                diffs.append(Difference(
                    path=path,
                    change_type=ChangeType.MODIFIED,
                    left_value=self._wrap_value(left_val, left_fd),
                    right_value=self._wrap_value(right_val, right_fd),
                    field_type=type_name(left_fd.type),
                ))
            return

        # Hook path — build context once, re-use across stages.
        ctx_state = _FieldHookState()
        ctx = FieldHookContext(
            path=path,
            left_fd=left_fd,
            right_fd=right_fd,
            left_value=left_val if left_present else None,
            right_value=right_val if right_present else None,
            left_msg=left_msg,
            right_msg=right_msg,
            left_pool=self._left_pool,
            right_pool=self._right_pool,
            _state=ctx_state,
        )

        # VALIDATE fires on every leaf evaluation, including
        # presence-gated paths (both-unset, one-sided add/remove).
        self._fire_field_stage(
            HookStage.VALIDATE, self._validate_hooks, ctx_state, ctx, warnings,
        )

        if left_has and right_has:
            # Same EQUAL/EQUIVALENT presence decision as the fast path (U5),
            # after VALIDATE has fired (SWI-6: VALIDATE fires on every leaf,
            # including presence-gated paths). COLLAPSE / EQUAL_PRESENCE-both-
            # unset drain warnings and return as equal; ADDED/REMOVED emit.
            verdict = presence_verdict(
                left_msg, right_msg, left_fd, right_fd,
                equal_mode=self._presence_mode == MessageFieldComparison.EQUAL,
                left_set=left_present, right_set=right_present,
            )
            if verdict is PresenceVerdict.COLLAPSE:
                self._drain_field_ctx_warnings(ctx_state, path, warnings)
                return
            if verdict is PresenceVerdict.EQUAL_PRESENCE and not left_present:
                # Both unset: nothing to compare.
                self._drain_field_ctx_warnings(ctx_state, path, warnings)
                return
            if verdict is PresenceVerdict.ADDED:
                diff = Difference(
                    path=path,
                    change_type=ChangeType.ADDED,
                    right_value=self._wrap_value(right_val, right_fd),
                    field_type=type_name(right_fd.type),
                )
                self._emit_with_report(
                    diff, ctx_state, ctx, diffs, warnings, path,
                )
                return
            if verdict is PresenceVerdict.REMOVED:
                diff = Difference(
                    path=path,
                    change_type=ChangeType.REMOVED,
                    left_value=self._wrap_value(left_val, left_fd),
                    field_type=type_name(left_fd.type),
                )
                self._emit_with_report(
                    diff, ctx_state, ctx, diffs, warnings, path,
                )
                return

        # Both present (or cross-schema presence asymmetry): run COMPARE.
        self._fire_field_stage(
            HookStage.COMPARE, self._compare_hooks, ctx_state, ctx, warnings,
        )
        if ctx_state.override_equal:
            equal = True
        else:
            equal = self._values_equal(
                left_val, right_val, left_fd, right_fd,
                same_pool, warnings, path,
            )
        if equal:
            self._drain_field_ctx_warnings(ctx_state, path, warnings)
            return

        diff = Difference(
            path=path,
            change_type=ChangeType.MODIFIED,
            left_value=self._wrap_value(left_val, left_fd),
            right_value=self._wrap_value(right_val, right_fd),
            field_type=type_name(left_fd.type),
        )
        self._emit_with_report(diff, ctx_state, ctx, diffs, warnings, path)

    def _compare_one_sided_scalar_with_hooks(
        self,
        value: Any,
        left_fd: proto_descriptor.FieldDescriptor,
        right_fd: proto_descriptor.FieldDescriptor,
        path: FieldPath,
        left_msg: Message,
        right_msg: Message,
        *,
        is_new: bool,
        diffs: list[Difference],
        warnings: list[Diagnostic],
    ) -> None:
        """Emit a one-sided scalar ADDED/REMOVED through the hook pipeline.

        Used by ``_compare_repeated`` extra elements and
        ``_compare_map`` one-sided keys so hooks see EVERY scalar
        leaf in a repeated/map field, not just the pairwise
        matches. VALIDATE fires with the absent side's value set
        to ``None`` in the context; COMPARE is skipped (presence
        change is structural, not overridable); REPORT fires on the
        diff.

        ``left_fd`` / ``right_fd`` are both the full field
        descriptors (the repeated field or the map's synthetic
        value sub-field) — the field itself exists on both sides,
        only this particular element/key is one-sided.
        """
        value_fd = right_fd if is_new else left_fd
        if is_new:
            diff = Difference(
                path=path, change_type=ChangeType.ADDED,
                right_value=self._wrap_value(value, value_fd),
                field_type=type_name(value_fd.type),
            )
            ctx_left_value: Any = None
            ctx_right_value: Any = value
        else:
            diff = Difference(
                path=path, change_type=ChangeType.REMOVED,
                left_value=self._wrap_value(value, value_fd),
                field_type=type_name(value_fd.type),
            )
            ctx_left_value = value
            ctx_right_value = None

        if not self._has_field_hooks():
            diffs.append(diff)
            return

        ctx_state = _FieldHookState()
        ctx = FieldHookContext(
            path=path,
            left_fd=left_fd,
            right_fd=right_fd,
            left_value=ctx_left_value,
            right_value=ctx_right_value,
            left_msg=left_msg,
            right_msg=right_msg,
            left_pool=self._left_pool,
            right_pool=self._right_pool,
            _state=ctx_state,
        )
        self._fire_field_stage(
            HookStage.VALIDATE, self._validate_hooks, ctx_state, ctx, warnings,
        )
        # COMPARE is skipped: a missing element is a structural
        # change, not something an equality override should rewrite.
        self._emit_with_report(diff, ctx_state, ctx, diffs, warnings, path)

    def _emit_one_sided_leaf_with_hooks(
        self,
        path: FieldPath,
        change_type: ChangeType,
        value: Any,
        fd: proto_descriptor.FieldDescriptor,
        parent_msg: Message,
        *,
        is_new: bool,
        diffs: list[Difference],
        warnings: list[Diagnostic],
    ) -> None:
        """Emit a leaf from a one-sided subtree/field through the hooks.

        Sibling of ``_compare_one_sided_scalar_with_hooks``, for the case
        where the leaf's whole *container* is absent on the other side —
        a sub-message present on one side only (``_emit_all_fields``) or a
        field that exists in only one schema (``_emit_one_sided``). Hook
        coverage must not depend on whether the parent happened to exist:
        the identical leaf already fires both stages when it is added
        under an already-present parent.

        Because the other side contributes neither a descriptor nor a
        parent message, ``left_fd``/``left_msg`` (or the right-hand pair)
        go into the context as ``None`` — the documented one-sided shape.

        VALIDATE fires; COMPARE is skipped (a presence change is
        structural, not something an equality override should rewrite);
        REPORT fires on the diff. Same stage discipline as the
        both-present one-sided element/key path.
        """
        diff = self._make_leaf_diff(path, change_type, value, fd, is_new=is_new)
        if not self._has_field_hooks():
            diffs.append(diff)
            return

        ctx_state = _FieldHookState()
        ctx = FieldHookContext(
            path=path,
            left_fd=None if is_new else fd,
            right_fd=fd if is_new else None,
            left_value=None if is_new else value,
            right_value=value if is_new else None,
            left_msg=None if is_new else parent_msg,
            right_msg=parent_msg if is_new else None,
            left_pool=self._left_pool,
            right_pool=self._right_pool,
            _state=ctx_state,
        )
        self._fire_field_stage(
            HookStage.VALIDATE, self._validate_hooks, ctx_state, ctx, warnings,
        )
        self._emit_with_report(diff, ctx_state, ctx, diffs, warnings, path)

    def _compare_scalar_pair_with_hooks(
        self,
        left_val: Any,
        right_val: Any,
        left_fd: proto_descriptor.FieldDescriptor,
        right_fd: proto_descriptor.FieldDescriptor,
        path: FieldPath,
        left_msg: Message,
        right_msg: Message,
        same_pool: bool,
        diffs: list[Difference],
        warnings: list[Diagnostic],
    ) -> None:
        """Compare a scalar-valued pair from a repeated or map field.

        Runs VALIDATE → COMPARE → ``_values_equal`` → REPORT when
        any field hooks are registered. Fast path inlines the
        original ``_values_equal`` + diff-append behavior. Used by
        both ``_compare_repeated`` (pairwise) and ``_compare_map``
        (native map) at their scalar-value call sites.

        ``left_msg`` / ``right_msg`` are the outer messages holding
        the repeated/map field — hooks that want the parent scope
        read these from the context. For map values the parent is
        the outer map's containing message, not the synthetic
        MapEntry.
        """
        if not self._has_field_hooks():
            equal = self._values_equal(
                left_val, right_val, left_fd, right_fd,
                same_pool, warnings, path,
            )
            if not equal:
                diffs.append(Difference(
                    path=path,
                    change_type=ChangeType.MODIFIED,
                    left_value=self._wrap_value(left_val, left_fd),
                    right_value=self._wrap_value(right_val, right_fd),
                    field_type=type_name(left_fd.type),
                ))
            return

        ctx_state = _FieldHookState()
        ctx = FieldHookContext(
            path=path,
            left_fd=left_fd,
            right_fd=right_fd,
            left_value=left_val,
            right_value=right_val,
            left_msg=left_msg,
            right_msg=right_msg,
            left_pool=self._left_pool,
            right_pool=self._right_pool,
            _state=ctx_state,
        )
        equal = self._run_validate_compare(
            ctx_state, ctx,
            left_val, right_val, left_fd, right_fd,
            same_pool, warnings, path,
        )
        if equal:
            self._drain_field_ctx_warnings(ctx_state, path, warnings)
            return

        diff = Difference(
            path=path,
            change_type=ChangeType.MODIFIED,
            left_value=self._wrap_value(left_val, left_fd),
            right_value=self._wrap_value(right_val, right_fd),
            field_type=type_name(left_fd.type),
        )
        self._emit_with_report(diff, ctx_state, ctx, diffs, warnings, path)

    def _selection_fd_for_float(
        self,
        left_fd: proto_descriptor.FieldDescriptor,
        path: FieldPath,
    ) -> proto_descriptor.FieldDescriptor:
        """Resolve the descriptor a float overlay selector should see (KTD-6).

        At a map element's value-compare site ``left_fd`` is the synthetic
        ``MapEntry.value`` descriptor (its ``name`` is ``"value"``), not the
        user's container field. A descriptor-predicate selector inspecting
        ``fd.name`` would therefore never match a map float value. This resolves
        the *container* field descriptor — the field on the parent message whose
        name is the path's last segment — so predicate-form selectors see the
        user's field name. (Path-form selectors already match via the path's
        bracket-blind last segment, so this matters only for the predicate form.)

        For repeated (non-map) float fields the element-compare site already
        passes the container descriptor, so ``left_fd`` is returned unchanged.

        Args:
            left_fd: The descriptor at the float-compare site.
            path: The concrete path of the value being compared.

        Returns:
            The container field descriptor for a map value, else ``left_fd``.
        """
        entry = left_fd.containing_type
        if entry is None or not entry.GetOptions().map_entry:
            return left_fd
        parent = entry.containing_type
        if parent is None or not path.segments:
            return left_fd
        container = parent.fields_by_name.get(path.segments[-1].name)
        return container if container is not None else left_fd

    def _float_config_for(
        self,
        left_fd: proto_descriptor.FieldDescriptor,
        path: FieldPath,
    ) -> FloatConfig:
        """Pick the FloatConfig for a float/double field (KTD-6/U6).

        Consults the per-field overlays FIRST: the first overlay whose selector
        matches ``(fd, path)`` supplies its config. Falls back to the global
        ``_float_config`` when no overlay matches — overlays LAYER over, never
        replace, the global setting (R11). Empty overlay list is a fast path.

        Args:
            left_fd: Field descriptor at the float-compare site.
            path: The concrete field path of the value being compared.

        Returns:
            The overlay's FloatConfig if one matches, else the global config.
        """
        if not self._float_overlays:
            return self._float_config
        selection_fd = self._selection_fd_for_float(left_fd, path)
        for selector, config in self._float_overlays:
            if selector.matches(selection_fd, path):
                return config
        return self._float_config

    def _values_equal(
        self,
        left: Any,
        right: Any,
        left_fd: proto_descriptor.FieldDescriptor,
        right_fd: proto_descriptor.FieldDescriptor,
        same_pool: bool,
        warnings: list[Diagnostic],
        path: FieldPath,
    ) -> bool:
        """Compare two field values for equality.

        Dispatches to the appropriate comparator based on field type
        (float, enum, or scalar).

        Args:
            left: The left field value.
            right: The right field value.
            left_fd: Field descriptor from the left schema.
            right_fd: Field descriptor from the right schema.
            same_pool: True if both messages share a descriptor pool.
            warnings: Accumulator list for Diagnostic objects (enum drift).
            path: The current field path for warning context.

        Returns:
            True if the values are considered equal.
        """
        if left_fd.type in (TYPE_FLOAT, TYPE_DOUBLE):
            return compare_float(
                float(left), float(right), self._float_config_for(left_fd, path)
            )

        if left_fd.type == TYPE_ENUM:
            if same_pool:
                return compare_enum_same_pool(left, right)
            left_ev = to_enum_value(left, left_fd.enum_type)
            right_ev = to_enum_value(right, right_fd.enum_type)
            equal, warning = compare_enum_cross_pool(
                left_ev.number, left_ev.name, right_ev.number, right_ev.name
            )
            if warning:
                warnings.append(Diagnostic(path=str(path), message=warning))
            return equal

        return compare_scalar(left, right)

    def _wrap_value(
        self,
        value: Any,
        fd: proto_descriptor.FieldDescriptor,
    ) -> Any:
        """Wrap a protobuf value for inclusion in a Difference.

        Converts enum integers to EnumValue; passes other types through.

        Args:
            value: The raw protobuf field value.
            fd: The field's descriptor.

        Returns:
            The value, possibly wrapped as an EnumValue.
        """
        if fd.type == TYPE_ENUM:
            return to_enum_value(value, fd.enum_type)
        return value

    def _make_leaf_diff(
        self,
        path: FieldPath,
        change_type: ChangeType,
        value: object,
        fd: proto_descriptor.FieldDescriptor,
        *,
        is_new: bool,
    ) -> Difference:
        """Build a leaf Difference, placing the value in left_value or right_value."""
        wrapped = self._wrap_value(value, fd)
        return Difference(
            path=path,
            change_type=change_type,
            left_value=None if is_new else wrapped,
            right_value=wrapped if is_new else None,
            field_type=type_name(fd.type),
        )

    def _compare_message_field(
        self,
        left_msg: Message,
        right_msg: Message,
        left_fd: proto_descriptor.FieldDescriptor,
        right_fd: proto_descriptor.FieldDescriptor,
        path: FieldPath,
        stack: list[_WorkItem],
        depth: int,
        diffs: list[Difference],
        warnings: list[Diagnostic],
        same_pool: bool,
    ) -> None:
        """Handle singular message field comparison.

        Checks presence on both sides and either emits leaf diffs or
        pushes a _WorkItem onto the stack for recursive comparison.

        Args:
            left_msg: The left parent message.
            right_msg: The right parent message.
            left_fd: Field descriptor from the left schema.
            right_fd: Field descriptor from the right schema.
            path: The current field path.
            stack: The iterative comparison work stack.
            depth: Current comparison depth.
            diffs: Accumulator list for Difference objects.
            warnings: Accumulator list for Diagnostic objects.
            same_pool: True if both messages share a descriptor pool.
        """
        left_present = left_msg.HasField(left_fd.name)
        right_present = right_msg.HasField(right_fd.name)

        if not left_present and not right_present:
            return
        if not left_present and right_present:
            # Partial gate (U4): an actual-only (right-only) sub-message is an
            # ADDED subtree — suppress it BEFORE pushing the separate recursive
            # walk, or partial would leak the whole subtree as added. Direction-
            # conditioned: only the right-only (ADDED) direction is dropped;
            # the left-only (REMOVED) branch below still reports (R5). The
            # right-only sub-message is by definition not present on expected,
            # so the partial gate always drops it here.
            if self._partial:
                return
            right_child = getattr(right_msg, right_fd.name)
            if _has_populated_fields(right_child):
                stack.append(_WorkItem(None, right_child, path, depth + 1))
            elif self._presence_mode == MessageFieldComparison.EQUAL:
                # Empty-but-present message exception. The set side is the
                # default (empty) instance. EQUAL distinguishes set-to-default
                # from unset → report ADDED. EQUIVALENT (the default) collapses
                # it (no diff) — the U5 reconciliation with this pre-existing
                # exception, layered here rather than re-emitted elsewhere so
                # there is exactly one decision site (no double-report).
                diffs.append(Difference(
                    path=path, change_type=ChangeType.ADDED,
                    field_type=type_name(right_fd.type),
                ))
            return
        if left_present and not right_present:
            left_child = getattr(left_msg, left_fd.name)
            if _has_populated_fields(left_child):
                stack.append(_WorkItem(left_child, None, path, depth + 1))
            elif self._presence_mode == MessageFieldComparison.EQUAL:
                # Symmetric empty-but-present REMOVED; EQUIVALENT collapses.
                diffs.append(Difference(
                    path=path, change_type=ChangeType.REMOVED,
                    field_type=type_name(left_fd.type),
                ))
            return

        # Both present: recurse
        stack.append(_WorkItem(
            getattr(left_msg, left_fd.name),
            getattr(right_msg, right_fd.name),
            path,
            depth + 1,
        ))

    def _compare_repeated(
        self,
        left_msg: Message,
        right_msg: Message,
        left_fd: proto_descriptor.FieldDescriptor,
        right_fd: proto_descriptor.FieldDescriptor,
        path: FieldPath,
        diffs: list[Difference],
        stack: list[_WorkItem],
        depth: int,
        warnings: list[Diagnostic],
        same_pool: bool,
    ) -> None:
        """Compare repeated fields using index-by-index or treat_as_map.

        If ``treat_as_map`` is configured for this field, delegates to
        ``_compare_treat_as_map``. Otherwise compares elements pairwise
        by index and reports extra/missing elements.

        Args:
            left_msg: The left parent message.
            right_msg: The right parent message.
            left_fd: Field descriptor from the left schema.
            right_fd: Field descriptor from the right schema.
            path: The current field path.
            diffs: Accumulator list for Difference objects.
            stack: The iterative comparison work stack.
            depth: Current comparison depth.
            warnings: Accumulator list for Diagnostic objects.
            same_pool: True if both messages share a descriptor pool.
        """
        field_name = left_fd.name

        # Check if treat_as_map is configured for this field
        key_field = self._get_treat_as_map_key(field_name, path)
        if key_field:
            if left_fd.type == TYPE_MESSAGE:
                self._compare_treat_as_map(
                    left_msg, right_msg, left_fd, right_fd, path,
                    key_field, diffs, stack, depth, warnings, same_pool,
                )
                return
            warnings.append(Diagnostic(
                path=str(path),
                message=f"treat_as_map configured but field is not a repeated message "
                        f"(type={type_name(left_fd.type)}); falling back to index comparison",
            ))

        # Keyless set comparison takes precedence over index pairing when the
        # field is set-marked (KTD-8/U3). treat_as_map (keyed) wins over set if
        # both somehow apply, since it returns above; the registration-time
        # conflict guard prevents path-form double-config.
        if self._treat_as_set_selectors and self._is_treat_as_set(path, left_fd):
            self._compare_treat_as_set(
                left_msg, right_msg, left_fd, right_fd, path,
                diffs, stack, depth, warnings, same_pool,
            )
            return

        left_list = getattr(left_msg, field_name)
        right_list = getattr(right_msg, field_name)

        min_len = min(len(left_list), len(right_list))

        # Compare pairwise
        for i in range(min_len):
            idx_path = _replace_bracket(path, str(i)) if path.segments else path

            if left_fd.type == TYPE_MESSAGE:
                stack.append(_WorkItem(left_list[i], right_list[i], idx_path, depth + 1))
            else:
                left_val = left_list[i]
                right_val = right_list[i]
                self._compare_scalar_pair_with_hooks(
                    left_val, right_val,
                    left_fd, right_fd,
                    idx_path,
                    left_msg, right_msg,
                    same_pool,
                    diffs, warnings,
                )

        # Extra elements present ONLY on actual (right). Under partial these
        # fall outside the expected sub-shape — actual is allowed to be a
        # superset (R5/U4) — so they are suppressed, consistent with how the
        # singular-field and whole-sub-message actual-only branches already
        # suppress under partial. In full mode they report as ADDED. (A
        # treat_as_set field has its own strict path and returns above, so this
        # guard never relaxes set membership — the KTD-8 carve-out is intact.)
        if not self._partial:
            for i in range(min_len, len(right_list)):
                idx_path = _replace_bracket(path, str(i)) if path.segments else path
                if right_fd.type == TYPE_MESSAGE:
                    if _has_populated_fields(right_list[i]):
                        stack.append(_WorkItem(None, right_list[i], idx_path, depth + 1))
                    else:
                        diffs.append(Difference(
                            path=idx_path, change_type=ChangeType.ADDED,
                            field_type=type_name(right_fd.type),
                        ))
                else:
                    self._compare_one_sided_scalar_with_hooks(
                        right_list[i], left_fd, right_fd, idx_path,
                        left_msg, right_msg, is_new=True,
                        diffs=diffs, warnings=warnings,
                    )

        for i in range(min_len, len(left_list)):
            idx_path = _replace_bracket(path, str(i)) if path.segments else path
            if left_fd.type == TYPE_MESSAGE:
                if _has_populated_fields(left_list[i]):
                    stack.append(_WorkItem(left_list[i], None, idx_path, depth + 1))
                else:
                    diffs.append(Difference(
                        path=idx_path, change_type=ChangeType.REMOVED,
                        field_type=type_name(left_fd.type),
                    ))
            else:
                self._compare_one_sided_scalar_with_hooks(
                    left_list[i], left_fd, right_fd, idx_path,
                    left_msg, right_msg, is_new=False,
                    diffs=diffs, warnings=warnings,
                )

    def _compare_map(
        self,
        left_msg: Message,
        right_msg: Message,
        left_fd: proto_descriptor.FieldDescriptor,
        right_fd: proto_descriptor.FieldDescriptor,
        path: FieldPath,
        diffs: list[Difference],
        stack: list[_WorkItem],
        depth: int,
        warnings: list[Diagnostic],
        same_pool: bool,
    ) -> None:
        """Compare native protobuf map fields.

        Iterates over the union of keys from both maps and reports added,
        removed, or modified entries.

        Args:
            left_msg: The left parent message.
            right_msg: The right parent message.
            left_fd: Field descriptor from the left schema.
            right_fd: Field descriptor from the right schema.
            path: The current field path.
            diffs: Accumulator list for Difference objects.
            stack: The iterative comparison work stack.
            depth: Current comparison depth.
            warnings: Accumulator list for Diagnostic objects.
            same_pool: True if both messages share a descriptor pool.
        """
        left_map = getattr(left_msg, left_fd.name)
        right_map = getattr(right_msg, right_fd.name)

        all_keys = left_map.keys() | right_map.keys()
        left_value_fd = left_fd.message_type.fields_by_name["value"]
        right_value_fd = right_fd.message_type.fields_by_name["value"]

        # Value-type change -> record the change, then skip value comparison.
        # The outer dispatch's ``_types_compatible`` gate only sees the map
        # field itself, which is TYPE_MESSAGE (the synthetic MapEntry) on both
        # sides no matter what the entry's value type is; a message->scalar
        # change therefore slips through and would push a raw scalar onto the
        # message work stack.
        #
        # Same disposition as the map<->repeated cardinality change: a
        # Difference for the schema change, and no value comparison. That
        # sibling gets its Difference from ``_check_schema_evolution``, which
        # runs before the skip — but that check is blind to the map's VALUE
        # type (both sides are the same synthetic MapEntry), so this branch has
        # to record it. Diagnosing alone would be worse than the crash it
        # replaced: ``has_changes()`` ignores diagnostics, so the comparison
        # would report EQUAL for two maps holding entirely different data.
        if not _types_compatible(left_value_fd.type, right_value_fd.type):
            diffs.append(Difference(
                path=path,
                change_type=ChangeType.TYPE_CHANGED,
                left_type=type_name(left_value_fd.type),
                right_type=type_name(right_value_fd.type),
            ))
            warnings.append(Diagnostic(
                path=str(path),
                message=f"map value type changed from "
                        f"{type_name(left_value_fd.type)} to "
                        f"{type_name(right_value_fd.type)}; values not compared",
            ))
            return

        for key in sorted(all_keys, key=lambda k: (type(k).__name__, k)):
            key_str = format_key(key)
            key_path = _replace_bracket(path, key_str) if path.segments else path

            if key not in left_map:
                # Actual-only key: outside the expected sub-shape under partial
                # (actual is allowed to be a superset, R5/U4) → suppressed.
                # Reported as ADDED only in full mode.
                if self._partial:
                    continue
                right_val = right_map[key]
                if right_value_fd.type == TYPE_MESSAGE:
                    if _has_populated_fields(right_val):
                        stack.append(_WorkItem(None, right_val, key_path, depth + 1))
                    else:
                        diffs.append(Difference(
                            path=key_path, change_type=ChangeType.ADDED,
                            field_type=type_name(right_value_fd.type),
                        ))
                else:
                    self._compare_one_sided_scalar_with_hooks(
                        right_val, left_value_fd, right_value_fd, key_path,
                        left_msg, right_msg, is_new=True,
                        diffs=diffs, warnings=warnings,
                    )
            elif key not in right_map:
                left_val = left_map[key]
                if left_value_fd.type == TYPE_MESSAGE:
                    if _has_populated_fields(left_val):
                        stack.append(_WorkItem(left_val, None, key_path, depth + 1))
                    else:
                        diffs.append(Difference(
                            path=key_path, change_type=ChangeType.REMOVED,
                            field_type=type_name(left_value_fd.type),
                        ))
                else:
                    self._compare_one_sided_scalar_with_hooks(
                        left_val, left_value_fd, right_value_fd, key_path,
                        left_msg, right_msg, is_new=False,
                        diffs=diffs, warnings=warnings,
                    )
            else:
                # Both have the key
                if left_value_fd.type == TYPE_MESSAGE:
                    stack.append(_WorkItem(
                        left_map[key], right_map[key], key_path, depth + 1,
                    ))
                else:
                    self._compare_scalar_pair_with_hooks(
                        left_map[key], right_map[key],
                        left_value_fd, right_value_fd,
                        key_path,
                        left_msg, right_msg,
                        same_pool,
                        diffs, warnings,
                    )

    def _set_elements_equal(
        self,
        left_elem: Any,
        right_elem: Any,
        left_fd: proto_descriptor.FieldDescriptor,
        right_fd: proto_descriptor.FieldDescriptor,
        same_pool: bool,
    ) -> bool:
        """Decide STRICT element equality for keyless set pairing (KTD-8).

        This is the equality callable injected into
        :func:`greedy_multiset_pairing`. It is backed by the engine so set
        membership matches :meth:`compare` semantics exactly — NOT a private
        reimplementation:

        * **Message elements** run a fresh, default-config sub-comparison
          (``MessageDifferencer().compare(...)``) and count "zero differences"
          as equal. The fresh differ carries default config (exact floats, no
          ignore/map/set/tolerance), so the comparison is strict yet still
          descriptor-aware: cross-pool name-matching, enum wire-compatibility,
          and presence all come from the engine. A one-field-different element
          therefore has differences and is NOT equal — it surfaces later as a
          remove + add pair, not a modify (documented v1 behavior).

        * **Scalar/enum/bytes elements** reuse the engine's value-equality path
          (:meth:`_values_equal` — same enum wire-compat / cross-pool logic),
          but under a STRICT float config so per-instance float tolerance never
          leaks into set-membership equality. Keeping equality strict makes it
          a true equivalence relation, so the greedy partition is
          order-independent (KTD-8).

        Args:
            left_elem: An element from the expected (left) list.
            right_elem: An element from the actual (right) list.
            left_fd: The repeated field's left descriptor.
            right_fd: The repeated field's right descriptor.
            same_pool: True if the parent messages share a descriptor pool.

        Returns:
            True if the two elements are strictly engine-equal.
        """
        if left_fd.type == TYPE_MESSAGE:
            # Engine equality for message elements: a fresh default-config
            # differ gives strict comparison with full descriptor awareness.
            sub_result = MessageDifferencer().compare(left_elem, right_elem)
            return not sub_result.has_changes()

        # Scalar/enum/bytes: engine value equality under a STRICT float config.
        if left_fd.type in (TYPE_FLOAT, TYPE_DOUBLE):
            return compare_float(
                float(left_elem), float(right_elem),
                _EXACT_FLOAT_CONFIG,
            )
        if left_fd.type == TYPE_ENUM:
            if same_pool:
                return compare_enum_same_pool(left_elem, right_elem)
            left_ev = to_enum_value(left_elem, left_fd.enum_type)
            right_ev = to_enum_value(right_elem, right_fd.enum_type)
            equal, _warning = compare_enum_cross_pool(
                left_ev.number, left_ev.name, right_ev.number, right_ev.name,
            )
            return equal
        return compare_scalar(left_elem, right_elem)

    def _compare_treat_as_set(
        self,
        left_msg: Message,
        right_msg: Message,
        left_fd: proto_descriptor.FieldDescriptor,
        right_fd: proto_descriptor.FieldDescriptor,
        path: FieldPath,
        diffs: list[Difference],
        stack: list[_WorkItem],
        depth: int,
        warnings: list[Diagnostic],
        same_pool: bool,
    ) -> None:
        """Compare a repeated field order-independently as a multiset (KTD-8).

        Pairs elements via :func:`greedy_multiset_pairing` with an engine-backed
        strict-equality callable (:meth:`_set_elements_equal`). Matched pairs
        emit nothing (they are strictly equal); leftovers reuse the existing
        element ``Difference`` shape — expected-side leftovers are REMOVED,
        actual-side leftovers are ADDED, each keyed by its original index in
        its own list (``field[i]``).

        Args:
            left_msg: The left parent message.
            right_msg: The right parent message.
            left_fd: Field descriptor from the left schema.
            right_fd: Field descriptor from the right schema.
            path: The current field path.
            diffs: Accumulator list for Difference objects.
            stack: The iterative comparison work stack.
            depth: Current comparison depth.
            warnings: Accumulator list for Diagnostic objects.
            same_pool: True if both messages share a descriptor pool.
        """
        left_list = list(getattr(left_msg, left_fd.name))
        right_list = list(getattr(right_msg, right_fd.name))

        def _equal(left_elem: Any, right_elem: Any) -> bool:
            return self._set_elements_equal(
                left_elem, right_elem, left_fd, right_fd, same_pool,
            )

        _matched, expected_unmatched, actual_unmatched = greedy_multiset_pairing(
            left_list, right_list, _equal,
        )

        # Expected-side leftovers -> REMOVED, keyed by original left index.
        for i in expected_unmatched:
            idx_path = _replace_bracket(path, str(i)) if path.segments else path
            if left_fd.type == TYPE_MESSAGE:
                if _has_populated_fields(left_list[i]):
                    stack.append(_WorkItem(left_list[i], None, idx_path, depth + 1))
                else:
                    diffs.append(Difference(
                        path=idx_path, change_type=ChangeType.REMOVED,
                        field_type=type_name(left_fd.type),
                    ))
            else:
                self._compare_one_sided_scalar_with_hooks(
                    left_list[i], left_fd, right_fd, idx_path,
                    left_msg, right_msg, is_new=False,
                    diffs=diffs, warnings=warnings,
                )

        # Actual-side leftovers -> ADDED, keyed by original right index.
        for i in actual_unmatched:
            idx_path = _replace_bracket(path, str(i)) if path.segments else path
            if right_fd.type == TYPE_MESSAGE:
                if _has_populated_fields(right_list[i]):
                    # force_emit: partial does NOT descend into set fields
                    # (KTD-8 carve-out), so an actual-only set message element
                    # must still report as ADDED even under partial scope.
                    stack.append(_WorkItem(
                        None, right_list[i], idx_path, depth + 1, force_emit=True,
                    ))
                else:
                    diffs.append(Difference(
                        path=idx_path, change_type=ChangeType.ADDED,
                        field_type=type_name(right_fd.type),
                    ))
            else:
                self._compare_one_sided_scalar_with_hooks(
                    right_list[i], left_fd, right_fd, idx_path,
                    left_msg, right_msg, is_new=True,
                    diffs=diffs, warnings=warnings,
                )

    def _compare_treat_as_map(
        self,
        left_msg: Message,
        right_msg: Message,
        left_fd: proto_descriptor.FieldDescriptor,
        right_fd: proto_descriptor.FieldDescriptor,
        path: FieldPath,
        key_field_name: str,
        diffs: list[Difference],
        stack: list[_WorkItem],
        depth: int,
        warnings: list[Diagnostic],
        same_pool: bool,
    ) -> None:
        """Compare a repeated message field using key-based matching.

        Elements are matched by extracting the configured key sub-field
        from each element. Unmatched keys are reported as added or removed.

        Args:
            left_msg: The left parent message.
            right_msg: The right parent message.
            left_fd: Field descriptor from the left schema.
            right_fd: Field descriptor from the right schema.
            path: The current field path.
            key_field_name: Name of the sub-field used as the map key.
            diffs: Accumulator list for Difference objects.
            stack: The iterative comparison work stack.
            depth: Current comparison depth.
            warnings: Accumulator list for Diagnostic objects.
            same_pool: True if both messages share a descriptor pool.
        """
        left_list = getattr(left_msg, left_fd.name)
        right_list = getattr(right_msg, right_fd.name)

        left_by_key = self._extract_keys(left_list, key_field_name, left_fd, path)
        right_by_key = self._extract_keys(right_list, key_field_name, right_fd, path)

        all_keys = left_by_key.keys() | right_by_key.keys()

        for key in sorted(all_keys, key=lambda k: (type(k).__name__, str(k))):
            key_bracket = f"{key_field_name}={format_key(key)}"
            key_path = _replace_bracket(path, key_bracket) if path.segments else path

            if key not in left_by_key:
                # Actual-only key: outside the expected sub-shape under partial
                # (actual is allowed to be a superset, R5/U4) → suppressed, as
                # in ``_compare_map``. Without this the populated element is
                # already suppressed downstream (its one-sided work item hits
                # the partial gate) while the EMPTY element leaks a vacuous
                # ADDED here. treat_as_map is a keyed collection, not a set, so
                # the KTD-8 carve-out does not apply.
                if self._partial:
                    continue
                right_elem = right_by_key[key]
                if _has_populated_fields(right_elem):
                    stack.append(_WorkItem(None, right_elem, key_path, depth + 1))
                else:
                    diffs.append(Difference(
                        path=key_path, change_type=ChangeType.ADDED,
                        field_type=type_name(right_fd.type),
                    ))
            elif key not in right_by_key:
                left_elem = left_by_key[key]
                if _has_populated_fields(left_elem):
                    stack.append(_WorkItem(left_elem, None, key_path, depth + 1))
                else:
                    diffs.append(Difference(
                        path=key_path, change_type=ChangeType.REMOVED,
                        field_type=type_name(left_fd.type),
                    ))
            else:
                stack.append(_WorkItem(
                    left_by_key[key], right_by_key[key], key_path, depth + 1,
                ))

    def _extract_keys(
        self,
        elements: Any,
        key_field_name: str,
        fd: proto_descriptor.FieldDescriptor,
        path: FieldPath,
    ) -> dict[Any, Message]:
        """Extract key values from repeated message elements.

        Args:
            elements: Iterable of protobuf Message elements.
            key_field_name: Name of the sub-field to use as key.
            fd: Field descriptor of the repeated field.
            path: The current field path (for error messages).

        Returns:
            A dict mapping each key value to its message element.

        Raises:
            ValueError: If the key field is not found in the descriptor.
            MissingKeyError: If an element is missing the key field.
            DuplicateKeyError: If two elements share the same key value.
        """
        result: dict[Any, Message] = {}
        key_fd = fd.message_type.fields_by_name.get(key_field_name)
        if key_fd is None:
            raise ValueError(
                f"key field '{key_field_name}' not found in descriptor "
                f"for {fd.message_type.full_name}"
            )

        for elem in elements:
            # Check presence for proto2/proto3 optional
            if has_presence(key_fd) and not elem.HasField(key_field_name):
                raise MissingKeyError(
                    f"Element in '{str(path)}' is missing key field '{key_field_name}'"
                )
            key_val = getattr(elem, key_field_name)
            if key_val in result:
                raise DuplicateKeyError(
                    f"Duplicate key '{key_val}' in '{str(path)}' "
                    f"for key field '{key_field_name}'"
                )
            result[key_val] = elem
        return result

    def _get_treat_as_map_key(self, field_name: str, field_path: FieldPath) -> str | None:
        """Get the key field name if treat_as_map is configured for this field.

        Checks path-scoped selectors first (bracket-stripped), then bare name.

        Args:
            field_name: The bare field name.
            field_path: The fully qualified field path.

        Returns:
            The key field name if configured, otherwise ``None``.
        """
        # Check path-scoped first (bracket-stripped segment name comparison),
        # then bare name
        for sel_path, key in self._treat_as_map_paths:
            if sel_path.matches_selector(field_path):
                return key
        if field_name in self._treat_as_map:
            return self._treat_as_map[field_name]
        return None

    def _is_treat_as_set(
        self,
        field_path: FieldPath,
        fd: proto_descriptor.FieldDescriptor,
    ) -> bool:
        """Whether this repeated field is configured for keyless set matching.

        Consults every registered :class:`FieldSelector` (path or predicate
        form) via the shared :meth:`FieldSelector.matches`. A predicate raising
        here PROPAGATES — it is an author bug, not an engine fault (KTD-10).

        Args:
            field_path: The fully qualified path of the repeated field.
            fd: The repeated field's descriptor (needed by predicate-form
                selectors).

        Returns:
            True if any configured ``treat_as_set`` selector matches.
        """
        for selector in self._treat_as_set_selectors:
            if selector.matches(fd, field_path):
                return True
        return False

    def _emit_all_fields(
        self,
        msg: Message,
        path: FieldPath,
        change_type: ChangeType,
        diffs: list[Difference],
        *,
        is_new: bool,
        warnings: list[Diagnostic],
        depth: int = 0,
        truncated_paths: list[FieldPath] | None = None,
    ) -> None:
        """Emit leaf-level diffs for all populated fields in a message.

        Used when an entire sub-message is added or removed, to report
        each populated leaf as its own Difference.

        Args:
            msg: The protobuf Message whose fields to emit.
            path: The path prefix for the emitted differences.
            change_type: ``ChangeType.ADDED`` or ``ChangeType.REMOVED``.
            diffs: Accumulator list for Difference objects.
            is_new: If True, values go into ``right_value``; otherwise
                ``left_value``.
            warnings: Accumulator list for Diagnostic objects (truncation,
                and anything raised or reported by a field hook — required
                because every leaf here is emitted through the hooks).
            depth: Current comparison depth for max_depth enforcement.
            truncated_paths: Accumulator list for truncated FieldPaths.
        """
        # Use an internal stack to handle arbitrary nesting depth.
        # Each entry: (message, path, depth)
        emit_stack: list[tuple[Message, FieldPath, int]] = [(msg, path, depth)]

        while emit_stack:
            cur_msg, cur_path, cur_depth = emit_stack.pop()

            # Max depth check
            if self.max_depth is not None and cur_depth > self.max_depth:
                if truncated_paths is not None:
                    truncated_paths.append(cur_path)
                warnings.append(Diagnostic(
                    path=str(cur_path) if cur_path else None,
                    message=f"comparison truncated at depth {self.max_depth}; "
                            "differences below this path are not reported",
                ))
                continue

            populated = cur_msg.ListFields()
            if not populated:
                # Empty-but-present message exception
                diffs.append(Difference(path=cur_path, change_type=change_type))
                continue

            for fd, value in populated:
                if fd.is_extension:
                    continue
                field_path = cur_path.child(fd.name)

                # Respect ignore_fields (string + predicate forms). The
                # descriptor is in hand here, so predicate selectors apply to
                # added/removed (one-sided) fields too — symmetric ignore.
                if self._is_ignored(fd.name, field_path, fd):
                    continue

                if is_map_field(fd):
                    # Native map field: iterate entries
                    value_fd = fd.message_type.fields_by_name["value"]
                    for k, v in value.items():
                        key_str = format_key(k)
                        key_path = _replace_bracket(field_path, key_str)
                        if value_fd.type == TYPE_MESSAGE:
                            if _has_populated_fields(v):
                                emit_stack.append((v, key_path, cur_depth + 1))
                            else:
                                diffs.append(Difference(
                                    path=key_path, change_type=change_type,
                                    field_type=type_name(value_fd.type),
                                ))
                        else:
                            self._emit_one_sided_leaf_with_hooks(
                                key_path, change_type, v, value_fd, cur_msg,
                                is_new=is_new, diffs=diffs, warnings=warnings,
                            )
                elif fd.type == TYPE_MESSAGE and not is_repeated(fd):
                    # Singular sub-message: push for full recursion
                    emit_stack.append((value, field_path, cur_depth + 1))
                elif is_repeated(fd):
                    # Check treat_as_map for key-based path formatting
                    tam_key = (
                        self._get_treat_as_map_key(fd.name, field_path)
                        if fd.type == TYPE_MESSAGE
                        else None
                    )
                    # Look up the key field descriptor once for the whole list
                    tam_key_fd = (
                        fd.message_type.fields_by_name.get(tam_key)
                        if tam_key
                        else None
                    )
                    if tam_key_fd is not None and tam_key is not None:
                        # Derive the keys through the same validator the
                        # two-sided path uses: ``compare()`` documents
                        # DuplicateKeyError / MissingKeyError unconditionally,
                        # so they must not depend on whether the other side
                        # happened to carry this subtree. Silently keying here
                        # collapsed duplicate-keyed elements onto one path and
                        # demoted a missing key to an index bracket.
                        keyed = self._extract_keys(value, tam_key, fd, field_path)
                        bracketed = [
                            (f"{tam_key}={format_key(key_val)}", elem)
                            for key_val, elem in keyed.items()
                        ]
                    else:
                        bracketed = [(str(i), elem) for i, elem in enumerate(value)]
                    for key_bracket, elem in bracketed:
                        elem_path = _replace_bracket(field_path, key_bracket)
                        if fd.type == TYPE_MESSAGE:
                            if _has_populated_fields(elem):
                                emit_stack.append((elem, elem_path, cur_depth + 1))
                            else:
                                diffs.append(Difference(
                                    path=elem_path, change_type=change_type,
                                    field_type=type_name(fd.type),
                                ))
                        else:
                            self._emit_one_sided_leaf_with_hooks(
                                elem_path, change_type, elem, fd, cur_msg,
                                is_new=is_new, diffs=diffs, warnings=warnings,
                            )
                else:
                    self._emit_one_sided_leaf_with_hooks(
                        field_path, change_type, value, fd, cur_msg,
                        is_new=is_new, diffs=diffs, warnings=warnings,
                    )

    def _emit_one_sided(
        self,
        msg: Message,
        fd: proto_descriptor.FieldDescriptor,
        path: FieldPath,
        diffs: list[Difference],
        stack: list[_WorkItem],
        depth: int,
        *,
        is_new: bool,
        warnings: list[Diagnostic],
    ) -> None:
        """Handle a field that only exists on one side (ADDED or REMOVED).

        Args:
            msg: The parent message containing the field.
            fd: Field descriptor for the one-sided field.
            path: The current field path.
            diffs: Accumulator list for Difference objects.
            stack: The iterative comparison work stack.
            depth: Current comparison depth.
            is_new: True for ADDED (right-only), False for REMOVED (left-only).
            warnings: Accumulator list for Diagnostic objects — every leaf
                here is emitted through the field hooks, which report
                raised/warned messages on this list.
        """
        change_type = ChangeType.ADDED if is_new else ChangeType.REMOVED

        def _work_item(child: Message, p: FieldPath) -> _WorkItem:
            if is_new:
                return _WorkItem(None, child, p, depth + 1)
            return _WorkItem(child, None, p, depth + 1)

        if fd.type == TYPE_MESSAGE and not is_repeated(fd):
            if msg.HasField(fd.name):
                child = getattr(msg, fd.name)
                if _has_populated_fields(child):
                    stack.append(_work_item(child, path))
                else:
                    diffs.append(Difference(
                        path=path, change_type=change_type,
                        field_type=type_name(fd.type),
                    ))
        elif is_map_field(fd):
            map_val = getattr(msg, fd.name)
            value_fd = fd.message_type.fields_by_name["value"]
            for k, v in map_val.items():
                key_str = format_key(k)
                key_path = _replace_bracket(path, key_str) if path.segments else path
                if value_fd.type == TYPE_MESSAGE:
                    if _has_populated_fields(v):
                        stack.append(_work_item(v, key_path))
                    else:
                        diffs.append(Difference(
                            path=key_path, change_type=change_type,
                            field_type=type_name(value_fd.type),
                        ))
                else:
                    self._emit_one_sided_leaf_with_hooks(
                        key_path, change_type, v, value_fd, msg,
                        is_new=is_new, diffs=diffs, warnings=warnings,
                    )
        elif is_repeated(fd):
            vals = getattr(msg, fd.name)
            for i, elem in enumerate(vals):
                idx_path = _replace_bracket(path, str(i)) if path.segments else path
                if fd.type == TYPE_MESSAGE:
                    if _has_populated_fields(elem):
                        stack.append(_work_item(elem, idx_path))
                    else:
                        diffs.append(Difference(
                            path=idx_path, change_type=change_type,
                            field_type=type_name(fd.type),
                        ))
                else:
                    self._emit_one_sided_leaf_with_hooks(
                        idx_path, change_type, elem, fd, msg,
                        is_new=is_new, diffs=diffs, warnings=warnings,
                    )
        else:
            val = getattr(msg, fd.name)
            # Skip unset fields: use HasField for presence-aware fields,
            # default-value check for proto3 implicit-presence fields
            if has_presence(fd):
                if not msg.HasField(fd.name):
                    return
            elif val == fd.default_value:
                return
            self._emit_one_sided_leaf_with_hooks(
                path, change_type, val, fd, msg,
                is_new=is_new, diffs=diffs, warnings=warnings,
            )


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _has_populated_fields(msg: Message) -> bool:
    """Check if a message has any populated fields.

    Args:
        msg: A protobuf Message.

    Returns:
        True if ``msg.ListFields()`` is non-empty.
    """
    return bool(msg.ListFields())


# ---------------------------------------------------------------------------
# Public API convenience function
# ---------------------------------------------------------------------------


def diff_messages(
    left: Message,
    right: Message,
    *,
    max_depth: int | None = None,
    strict_schema: bool = False,
) -> DiffResult:
    """Compare two protobuf messages and return a DiffResult.

    Convenience function that creates a MessageDifferencer with the given options.

    Args:
        left: The left-side protobuf ``Message`` (old/expected).
        right: The right-side protobuf ``Message`` (new/actual).
        max_depth: Maximum comparison depth. ``None`` (the default)
            means unlimited; subtrees below the limit are not
            compared and their paths appear in
            ``DiffResult.truncated_paths``.
        strict_schema: When True, emit a ``Diagnostic`` if the two
            messages have different fully-qualified type names.
            Defaults to False.

    Returns:
        A ``DiffResult`` with differences, warnings, and truncation
        markers. Differences are sorted by path.

    Raises:
        DuplicateKeyError: If ``treat_as_map`` were configured on
            the differencer (not possible via this convenience
            function; use ``MessageDifferencer`` directly).
    """
    differ = MessageDifferencer()
    if max_depth is not None:
        differ.max_depth = max_depth
    differ.strict_schema = strict_schema
    return differ.compare(left, right)
