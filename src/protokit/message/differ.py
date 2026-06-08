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
from protokit.message.comparators import (
    FloatComparison,
    FloatConfig,
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


# ---------------------------------------------------------------------------
# Work item for the iterative stack
# ---------------------------------------------------------------------------

@dataclass
class _WorkItem:
    """A unit of comparison work for the stack-based engine."""

    left_msg: Message | None
    right_msg: Message | None
    path: FieldPath
    depth: int


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
        self._treat_as_map: dict[str, str] = {}  # field_name_or_path -> key_field_name
        self._treat_as_map_paths: list[tuple[FieldPath, str]] = []  # (parsed_path, key_name)
        self._float_config = FloatConfig()
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

    def ignore_fields(self, *selectors: str) -> None:
        """Add field name selectors to the ignore list.

        Bare names apply globally. Dotted paths match specific locations.

        Args:
            *selectors: One or more field selectors. A bare name (e.g.
                ``"timestamp"``) ignores that field everywhere. A dotted
                path (e.g. ``"header.timestamp"``) ignores only that
                specific location.

        Raises:
            ValueError: If a selector conflicts with a ``treat_as_map``
                configuration (e.g. ignoring a map key field).
        """
        # Validate all selectors before mutating state
        for sel in selectors:
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
            for ign in selectors:
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
        self._ignore_fields_raw.extend(selectors)
        for sel in selectors:
            if "." in sel:
                self._ignore_paths.append(FieldPath.parse(sel))
            else:
                self._ignore_names.add(sel)

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

        self._treat_as_map[field_selector] = key
        if "." in field_selector:
            self._treat_as_map_paths.append((FieldPath.parse(field_selector), key))

    def set_float_comparison(
        self,
        mode: FloatComparison,
        fraction: float = 1e-6,
        margin: float = 1e-9,
    ) -> None:
        """Configure how float (and double) fields are compared.

        Default is exact IEEE 754 comparison.

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
        """
        self._float_config = FloatConfig(mode=mode, fraction=fraction, margin=margin)

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

                for field_name in sorted_names:
                    # Fast path: check bare-name ignore before allocating FieldPath
                    if field_name in self._ignore_names:
                        continue
                    field_path = item.path.child(field_name)

                    # Check path-scoped ignores
                    if self._ignore_paths and self._is_ignored(field_name, field_path):
                        continue

                    left_fd = left_fields.get(field_name)
                    right_fd = right_fields.get(field_name)

                    # Field only on one side
                    if left_fd is None and right_fd is not None:
                        self._emit_one_sided(
                            item.right_msg, right_fd, field_path,
                            differences, stack, item.depth, is_new=True,
                        )
                        continue
                    if left_fd is not None and right_fd is None:
                        self._emit_one_sided(
                            item.left_msg, left_fd, field_path,
                            differences, stack, item.depth, is_new=False,
                        )
                        continue

                    assert left_fd is not None and right_fd is not None

                    # Schema evolution checks
                    self._check_schema_evolution(
                        left_fd, right_fd, field_path, differences, warnings
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

    def _is_ignored(self, field_name: str, field_path: FieldPath) -> bool:
        """Check if a field should be ignored.

        Args:
            field_name: The bare field name.
            field_path: The fully qualified field path.

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
        return False

    def _check_schema_evolution(
        self,
        left_fd: proto_descriptor.FieldDescriptor,
        right_fd: proto_descriptor.FieldDescriptor,
        path: FieldPath,
        diffs: list[Difference],
        warnings: list[Diagnostic],
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

        # Strict schema: message type name mismatch warning
        if (
            self.strict_schema
            and left_fd.type == TYPE_MESSAGE
            and right_fd.type == TYPE_MESSAGE
            and left_fd.message_type.full_name != right_fd.message_type.full_name
        ):
            warnings.append(Diagnostic(
                path=str(path),
                message=(
                    f"message type name changed: "
                    f"{left_fd.message_type.full_name} -> "
                    f"{right_fd.message_type.full_name}"
                ),
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
                if not left_present and not right_present:
                    return
                if not left_present and right_present:
                    diffs.append(Difference(
                        path=path,
                        change_type=ChangeType.ADDED,
                        right_value=self._wrap_value(right_val, right_fd),
                        field_type=type_name(right_fd.type),
                    ))
                    return
                if left_present and not right_present:
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
            if not left_present and not right_present:
                self._drain_field_ctx_warnings(ctx_state, path, warnings)
                return
            if not left_present and right_present:
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
            if left_present and not right_present:
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
            return compare_float(float(left), float(right), self._float_config)

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
            right_child = getattr(right_msg, right_fd.name)
            if _has_populated_fields(right_child):
                stack.append(_WorkItem(None, right_child, path, depth + 1))
            else:
                # Empty-but-present message exception
                diffs.append(Difference(
                    path=path, change_type=ChangeType.ADDED,
                    field_type=type_name(right_fd.type),
                ))
            return
        if left_present and not right_present:
            left_child = getattr(left_msg, left_fd.name)
            if _has_populated_fields(left_child):
                stack.append(_WorkItem(left_child, None, path, depth + 1))
            else:
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

        # Extra elements
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

        for key in sorted(all_keys, key=lambda k: (type(k).__name__, k)):
            key_str = format_key(key)
            key_path = _replace_bracket(path, key_str) if path.segments else path

            if key not in left_map:
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

    def _emit_all_fields(
        self,
        msg: Message,
        path: FieldPath,
        change_type: ChangeType,
        diffs: list[Difference],
        *,
        is_new: bool,
        depth: int = 0,
        warnings: list[Diagnostic] | None = None,
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
            depth: Current comparison depth for max_depth enforcement.
            warnings: Accumulator list for Diagnostic objects (truncation).
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
                if warnings is not None:
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

                # Respect ignore_fields
                if self._is_ignored(fd.name, field_path):
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
                            diffs.append(self._make_leaf_diff(
                                key_path, change_type, v, value_fd, is_new=is_new,
                            ))
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
                    for i, elem in enumerate(value):
                        if tam_key_fd and fd.type == TYPE_MESSAGE:
                            # Use presence-aware check consistent with _extract_keys
                            if not has_presence(tam_key_fd) or elem.HasField(tam_key):
                                key_val = getattr(elem, tam_key)
                                key_bracket = f"{tam_key}={format_key(key_val)}"
                            else:
                                key_bracket = str(i)
                            elem_path = _replace_bracket(field_path, key_bracket)
                        else:
                            elem_path = _replace_bracket(field_path, str(i))
                        if fd.type == TYPE_MESSAGE:
                            if _has_populated_fields(elem):
                                emit_stack.append((elem, elem_path, cur_depth + 1))
                            else:
                                diffs.append(Difference(
                                    path=elem_path, change_type=change_type,
                                    field_type=type_name(fd.type),
                                ))
                        else:
                            diffs.append(self._make_leaf_diff(
                                elem_path, change_type, elem, fd, is_new=is_new,
                            ))
                else:
                    diffs.append(self._make_leaf_diff(
                        field_path, change_type, value, fd, is_new=is_new,
                    ))

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
                    diffs.append(self._make_leaf_diff(
                        key_path, change_type, v, value_fd, is_new=is_new,
                    ))
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
                    diffs.append(self._make_leaf_diff(
                        idx_path, change_type, elem, fd, is_new=is_new,
                    ))
        else:
            val = getattr(msg, fd.name)
            # Skip unset fields: use HasField for presence-aware fields,
            # default-value check for proto3 implicit-presence fields
            if has_presence(fd):
                if not msg.HasField(fd.name):
                    return
            elif val == fd.default_value:
                return
            diffs.append(self._make_leaf_diff(
                path, change_type, val, fd, is_new=is_new,
            ))


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
