"""Data model for protobuf message diffs.

Pure data structures with zero protobuf imports. All descriptor-aware logic
lives in differ.py.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable, Iterator

if TYPE_CHECKING:  # pragma: no cover — typing-only imports
    from google.protobuf import descriptor as proto_descriptor
    from google.protobuf import descriptor_pool
    from google.protobuf.message import Message


class ChangeType(Enum):
    """Classification of a single difference between two messages.

    Members:
        ADDED: A field is set on the right side and unset on the left.
            ``Difference.new_value`` carries the value.
        REMOVED: A field is set on the left side and unset on the
            right. ``Difference.old_value`` carries the value.
        MODIFIED: Both sides have the field but the values differ.
            Both ``old_value`` and ``new_value`` are populated.
        TYPE_CHANGED: Same field name on both sides but the field
            type differs. ``left_type`` and ``right_type`` are
            populated; only fires under cross-pool comparison.
        FIELD_NUMBER_CHANGED: Same field name on both sides but
            different field numbers. ``left_field_number`` and
            ``right_field_number`` are populated.
        CARDINALITY_CHANGED: Same field name on both sides but the
            label flipped (e.g. singular -> repeated). ``left_label``
            and ``right_label`` are populated.
    """

    ADDED = "ADDED"
    REMOVED = "REMOVED"
    MODIFIED = "MODIFIED"
    TYPE_CHANGED = "TYPE_CHANGED"
    FIELD_NUMBER_CHANGED = "FIELD_NUMBER_CHANGED"
    CARDINALITY_CHANGED = "CARDINALITY_CHANGED"


@dataclass(frozen=True)
class EnumValue:
    """A protobuf enum value carrying both its name and its number.

    Used in ``Difference.old_value`` / ``Difference.new_value`` for
    enum fields so consumers can render either or both without
    re-resolving from the descriptor pool.

    Attributes:
        name: The enum value's identifier as written in the
            ``.proto`` (e.g. ``"ACTIVE"``).
        number: The enum value's wire number (e.g. ``1``).
    """

    name: str
    number: int

    def __str__(self) -> str:
        """Render as ``NAME(number)`` for human display.

        Returns:
            A string like ``"ACTIVE(1)"``.
        """
        return f"{self.name}({self.number})"


@dataclass(frozen=True)
class Warning:
    """A non-diff diagnostic surfaced alongside a ``DiffResult``.

    Warnings are used for situations the engine wants to flag but
    that are not themselves differences — e.g., a fallback to
    index-based comparison when ``treat_as_map`` is configured but
    the key field has unsupported type, or a synthetic-oneof edge
    case during cross-pool comparison.

    Attributes:
        path: Dotted-path string identifying where the warning
            applies, or ``None`` for warnings about the message as a
            whole.
        message: Human-readable explanation.
    """

    path: str | None
    message: str

    def __str__(self) -> str:
        """Render as ``path: message`` (or just ``message`` when path is None).

        Returns:
            A formatted single-line string.
        """
        if self.path:
            return f"{self.path}: {self.message}"
        return self.message


class DuplicateKeyError(ValueError):
    """Raised when ``treat_as_map`` encounters duplicate keys.

    A repeated field configured with ``treat_as_map`` must have
    unique key values on each side; duplicates make matching
    ambiguous. The exception message includes the duplicated key
    value and the field path.
    """


class MissingKeyError(ValueError):
    """Raised when ``treat_as_map`` encounters an element missing the key field.

    Fires when an entry in a ``treat_as_map``-configured repeated
    field has its designated key field unset (e.g. proto2 optional
    not populated). The exception message includes the field path
    and the offending element index.
    """


# ---------------------------------------------------------------------------
# FieldPath: unified path grammar for all protobuf field paths
# ---------------------------------------------------------------------------

# Grammar:
#   path     := segment ('.' segment)*
#   segment  := name bracket?
#   name     := [a-zA-Z_][a-zA-Z0-9_]*
#   bracket  := '[' key ']'
#   key      := signed_int | bool_lit | quoted_string | key_eq
#   signed_int := '-'? [0-9]+
#   bool_lit := 'true' | 'false'
#   quoted_string := '"' escaped_chars '"'
#   key_eq   := name '=' (signed_int | bool_lit | quoted_string)

_NAME_RE = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*")


@dataclass(frozen=True)
class PathSegment:
    """One element of a parsed ``FieldPath``: a name plus optional bracket.

    Brackets carry runtime detail that descriptor-only paths never
    use — repeated indices, map keys, ``treat_as_map`` keyed lookups.
    Plain field names have ``bracket == None``.

    Attributes:
        name: The field's identifier (matches ``[a-zA-Z_][a-zA-Z0-9_]*``).
        bracket: Raw bracket content as it appeared in the source
            string. Examples: ``"2"`` (repeated index), ``'"env"'``
            (quoted string map key), ``"true"`` (bool map key),
            ``"id=42"`` (key-equals-value form for ``treat_as_map``).
            ``None`` when the segment has no bracket.
    """

    name: str
    bracket: str | None = None

    def __str__(self) -> str:
        """Render the segment back to its source form.

        Returns:
            ``"name"`` or ``"name[bracket]"`` depending on whether
            ``bracket`` is set.
        """
        if self.bracket is not None:
            return f"{self.name}[{self.bracket}]"
        return self.name

    def matches(self, other: PathSegment, *, exact: bool = False) -> bool:
        """Check if this segment matches another for filtering.

        In prefix mode (exact=False): a segment without bracket matches any
        segment with the same name regardless of bracket content.
        A segment WITH bracket matches only segments with same name AND bracket.

        In exact mode: bracket must also match (None only matches None).

        Args:
            other: The PathSegment to compare against.
            exact: If True, require bracket equality. If False (default),
                a None bracket acts as a wildcard.

        Returns:
            True if this segment matches ``other`` under the chosen mode.
        """
        if self.name != other.name:
            return False
        if exact:
            return self.bracket == other.bracket
        # Prefix mode: no bracket on filter = wildcard
        if self.bracket is None:
            return True
        return self.bracket == other.bracket


@dataclass(frozen=True)
class FieldPath:
    """A parsed, immutable protobuf field path.

    Used both by message diffing (which produces paths with bracket
    indices and map keys) and by schema checking (which uses pure
    dotted names). The empty path (``segments == ()``) refers to the
    root message and renders as ``""``.

    Attributes:
        segments: Tuple of ``PathSegment`` objects, in source order.
            The empty tuple represents the root path.
    """

    segments: tuple[PathSegment, ...]

    @staticmethod
    def parse(path_str: str) -> FieldPath:
        """Parse a dotted path string into a FieldPath.

        Args:
            path_str: A dotted field path such as ``"user.name"`` or
                ``"items[2].name"``. An empty string yields an empty path.

        Returns:
            A FieldPath with one PathSegment per dot-separated component.

        Raises:
            ValueError: If the path string is malformed (e.g. trailing dot,
                unclosed bracket, unexpected character).

        Examples:
            "user.name" -> FieldPath([PathSegment("user"), PathSegment("name")])
            "items[2].name" -> FieldPath([PathSegment("items", "2"), PathSegment("name")])
            'labels["env"]' -> FieldPath([PathSegment("labels", '"env"')])
            "items[id=42]" -> FieldPath([PathSegment("items", "id=42")])
        """
        if not path_str:
            return FieldPath(segments=())

        segments: list[PathSegment] = []
        pos = 0
        length = len(path_str)

        while pos < length:
            # Parse name
            m = _NAME_RE.match(path_str, pos)
            if not m:
                raise ValueError(f"Expected field name at position {pos} in '{path_str}'")
            name = m.group()
            pos = m.end()

            # Parse optional bracket
            bracket = None
            if pos < length and path_str[pos] == "[":
                bracket_start = pos + 1
                # Find matching ]
                bracket_end = _find_closing_bracket(path_str, pos)
                bracket = path_str[bracket_start:bracket_end]
                pos = bracket_end + 1

            segments.append(PathSegment(name=name, bracket=bracket))

            # Expect '.' or end
            if pos < length:
                if path_str[pos] == ".":
                    pos += 1
                    if pos >= length:
                        raise ValueError(f"Trailing '.' in '{path_str}'")
                else:
                    raise ValueError(
                        f"Expected '.' or end at position {pos} in '{path_str}'"
                    )

        return FieldPath(segments=tuple(segments))

    def child(self, name: str, bracket: str | None = None) -> FieldPath:
        """Create a new path with an additional segment appended.

        Args:
            name: Field name for the new segment.
            bracket: Optional bracket content (e.g. ``"2"`` or ``'"key"'``).

        Returns:
            A new FieldPath with the extra segment at the end.
        """
        return FieldPath(
            segments=self.segments + (PathSegment(name=name, bracket=bracket),)
        )

    def is_prefix_of(self, other: FieldPath) -> bool:
        """Check if this path is a prefix of another (segment-aware).

        Args:
            other: The candidate longer path.

        Returns:
            True if every segment of ``self`` matches the corresponding
            segment of ``other`` in prefix (wildcard-bracket) mode.
        """
        if len(self.segments) > len(other.segments):
            return False
        for self_seg, other_seg in zip(self.segments, other.segments):
            if not self_seg.matches(other_seg, exact=False):
                return False
        return True

    def matches_exact(self, other: FieldPath) -> bool:
        """Check if this path matches another exactly.

        Args:
            other: The path to compare against.

        Returns:
            True if both paths have the same number of segments and each
            pair matches with exact bracket equality.
        """
        if len(self.segments) != len(other.segments):
            return False
        for self_seg, other_seg in zip(self.segments, other.segments):
            if not self_seg.matches(other_seg, exact=True):
                return False
        return True

    def __str__(self) -> str:
        """Render the path back to its dotted source form.

        Returns:
            Dot-joined segment string (e.g. ``"user.address[0].city"``).
            The empty path returns the empty string.
        """
        return ".".join(str(seg) for seg in self.segments)

    def __bool__(self) -> bool:
        """Truthiness reflects whether the path has any segments.

        Returns:
            False for the root path (no segments), True otherwise.
        """
        return bool(self.segments)


def _find_closing_bracket(s: str, open_pos: int) -> int:
    """Find the position of the closing ']', handling quoted strings.

    Args:
        s: The full path string being parsed.
        open_pos: Index of the opening ``[`` character.

    Returns:
        Index of the matching ``]`` character.

    Raises:
        ValueError: If no closing bracket is found.
    """
    pos = open_pos + 1
    length = len(s)
    while pos < length:
        ch = s[pos]
        if ch == "]":
            return pos
        if ch == '"':
            # Skip quoted string
            pos += 1
            while pos < length:
                if s[pos] == "\\":
                    pos += 2
                    continue
                if s[pos] == '"':
                    break
                pos += 1
        pos += 1
    raise ValueError(f"Unclosed bracket starting at position {open_pos} in '{s}'")


# ---------------------------------------------------------------------------
# Difference and DiffResult
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Difference:
    """A single difference between two protobuf messages.

    Which of the optional fields are populated depends on
    ``change_type``:

    - ``ADDED``: ``new_value`` set; ``field_type`` describes the
      field's type.
    - ``REMOVED``: ``old_value`` set; ``field_type`` describes it.
    - ``MODIFIED``: both ``old_value`` and ``new_value`` set.
    - ``TYPE_CHANGED``: ``left_type`` / ``right_type`` set.
    - ``FIELD_NUMBER_CHANGED``: ``left_field_number`` /
      ``right_field_number`` set.
    - ``CARDINALITY_CHANGED``: ``left_label`` / ``right_label`` set.

    Attributes:
        path: ``FieldPath`` to the field that differs. The empty
            path means the difference is at the root message.
        change_type: One of ``ChangeType`` — controls which optional
            attributes carry meaningful values.
        old_value: Value on the left/old side. Set for ``REMOVED``
            and ``MODIFIED``; ``None`` otherwise.
        new_value: Value on the right/new side. Set for ``ADDED``
            and ``MODIFIED``; ``None`` otherwise.
        field_type: Human-readable protobuf type name (e.g.
            ``"TYPE_STRING"``) for ``ADDED`` / ``REMOVED`` /
            ``MODIFIED``. ``None`` for schema-evolution change types.
        left_field_number: Old-side field number, set for
            ``FIELD_NUMBER_CHANGED``.
        right_field_number: New-side field number, set for
            ``FIELD_NUMBER_CHANGED``.
        left_type: Old-side type name, set for ``TYPE_CHANGED``.
        right_type: New-side type name, set for ``TYPE_CHANGED``.
        left_label: Old-side cardinality label (``"singular"`` /
            ``"repeated"`` / ``"map"``), set for
            ``CARDINALITY_CHANGED``.
        right_label: New-side cardinality label, set for
            ``CARDINALITY_CHANGED``.
    """

    path: FieldPath
    change_type: ChangeType
    old_value: object | None = None
    new_value: object | None = None
    field_type: str | None = None

    # Schema evolution extra fields
    left_field_number: int | None = None
    right_field_number: int | None = None
    left_type: str | None = None
    right_type: str | None = None
    left_label: str | None = None
    right_label: str | None = None

    # Phase 1.5 differ hook annotations
    annotations: tuple[str, ...] = ()

    def __str__(self) -> str:
        """Render a single-line summary using a per-change-type prefix.

        Prefix legend: ``+`` added, ``-`` removed, ``~`` modified,
        ``T`` type changed, ``#`` field number changed,
        ``C`` cardinality changed. When ``annotations`` is
        non-empty, annotations are appended in brackets separated
        by ``; ``.

        Returns:
            A single-line string suitable for CLI output. Empty
            paths render as ``(root)``.
        """
        path_str = str(self.path) if self.path else "(root)"
        match self.change_type:
            case ChangeType.ADDED:
                base = f"+ {path_str}: {self.new_value}"
            case ChangeType.REMOVED:
                base = f"- {path_str}: {self.old_value}"
            case ChangeType.MODIFIED:
                base = f"~ {path_str}: {self.old_value} -> {self.new_value}"
            case ChangeType.TYPE_CHANGED:
                base = f"T {path_str}: {self.left_type} -> {self.right_type}"
            case ChangeType.FIELD_NUMBER_CHANGED:
                base = f"# {path_str}: field {self.left_field_number} -> {self.right_field_number}"
            case ChangeType.CARDINALITY_CHANGED:
                base = f"C {path_str}: {self.left_label} -> {self.right_label}"
            case _:
                base = f"? {path_str}: {self.change_type.value}"
        if self.annotations:
            return f"{base} [{'; '.join(self.annotations)}]"
        return base


@dataclass(frozen=True)
class DiffResult:
    """Immutable, filterable collection of differences.

    Returned by ``MessageDifferencer.compare()`` /
    ``diff_messages()``. All filter methods return new instances —
    the original is never mutated, so the same ``DiffResult`` can be
    passed around freely and filtered multiple ways.

    Attributes:
        differences: Tuple of ``Difference`` objects in traversal
            order. Empty tuple means the messages compared equal.
        warnings: Tuple of ``Warning`` diagnostics emitted during
            comparison. Defaults to empty.
        truncated_paths: Tuple of paths where ``max_depth`` cut off
            the traversal. Empty when the comparison ran to the
            leaves. See ``is_complete``.
    """

    differences: tuple[Difference, ...]
    warnings: tuple[Warning, ...] = ()
    truncated_paths: tuple[FieldPath, ...] = ()

    @property
    def is_complete(self) -> bool:
        """Whether the comparison ran to completion without truncation.

        Returns:
            True iff ``truncated_paths`` is empty. False indicates
            ``MessageDifferencer.max_depth`` cut off one or more
            subtrees before reaching the leaves.
        """
        return not self.truncated_paths

    def has_changes(self) -> bool:
        """Report whether any differences were found.

        Returns:
            True when ``differences`` is non-empty.
        """
        return bool(self.differences)

    def field_paths(self) -> list[FieldPath]:
        """Return the path of every difference, in traversal order.

        Returns:
            A new list of ``FieldPath`` objects, one per difference,
            preserving the order of ``differences``.
        """
        return [d.path for d in self.differences]

    def filter(
        self,
        *,
        path: str | None = None,
        change_type: ChangeType | None = None,
        exact: bool = False,
    ) -> DiffResult:
        """Return a new DiffResult containing only matching differences.

        Args:
            path: Dotted path string for filtering. Uses segment-aware
                prefix matching by default, or exact matching when
                ``exact=True``. ``None`` means no path filtering.
            change_type: If given, only differences of this type are kept.
            exact: When True, ``path`` must match the difference path
                exactly rather than as a prefix.

        Returns:
            A new DiffResult with the filtered subset of differences
            and warnings. ``truncated_paths`` are carried over unchanged.
        """
        diffs = self.differences
        warnings = self.warnings

        if path is not None:
            filter_path = FieldPath.parse(path)
            if exact:
                diffs = tuple(d for d in diffs if filter_path.matches_exact(d.path))
                warnings = tuple(
                    w
                    for w in warnings
                    if w.path is None or filter_path.matches_exact(FieldPath.parse(w.path))
                )
            else:
                diffs = tuple(d for d in diffs if filter_path.is_prefix_of(d.path))
                warnings = tuple(
                    w
                    for w in warnings
                    if w.path is None or filter_path.is_prefix_of(FieldPath.parse(w.path))
                )

        if change_type is not None:
            diffs = tuple(d for d in diffs if d.change_type == change_type)

        return DiffResult(
            differences=diffs,
            warnings=warnings,
            truncated_paths=self.truncated_paths,
        )

    def __len__(self) -> int:
        """Return the number of differences.

        Returns:
            ``len(self.differences)``.
        """
        return len(self.differences)

    def __iter__(self) -> Iterator[Difference]:
        """Iterate over differences in traversal order.

        Returns:
            An iterator over ``self.differences``.
        """
        return iter(self.differences)

    def __bool__(self) -> bool:
        """Truthiness reflects presence of differences.

        Returns:
            True iff at least one difference was found.
        """
        return self.has_changes()


# ---------------------------------------------------------------------------
# Phase 1.5 — Differ hook pipeline types
# ---------------------------------------------------------------------------


class HookStage(Enum):
    """Which stage of the comparison pipeline a hook is firing in.

    The engine fires stages in fixed order per field:
    ``VALIDATE`` → ``COMPARE`` → ``REPORT``. Each stage has its own
    list of hooks on the ``MessageDifferencer``. Hooks receive the
    same ``FieldHookContext`` object across stages (``_state.stage``
    tells them which stage they're in) but the context's
    ``override_equal()`` / ``annotate()`` methods only take effect
    at their corresponding stages.

    Members:
        VALIDATE: Pre-compare. Hooks call ``ctx.warn(...)`` to flag
            constraint violations on either side. Fires on every
            leaf evaluation — including presence-gated early
            returns (both-unset, one-sided add/remove).
        COMPARE: During compare. Hooks call ``ctx.override_equal()``
            to treat the two values as equal regardless of what
            ``_values_equal`` would say. Only fires when both
            values are present (not on presence-gated paths —
            presence is structural, not overridable).
        REPORT: Post-compare. Hooks call ``ctx.annotate(...)`` to
            attach an annotation string to the ``Difference`` about
            to be emitted. Only fires when a diff is being emitted
            (values not equal, or presence-gated add/remove).
    """

    VALIDATE = "VALIDATE"
    COMPARE = "COMPARE"
    REPORT = "REPORT"


class _FieldHookState:
    """Engine-internal mutable scratch space for a ``FieldHookContext``.

    The context dataclass is frozen; hook state (current stage,
    whether a diff is being produced, warnings emitted, override
    and annotation requests) lives on this companion object that
    the engine mutates between stages. Hook code never touches
    ``_FieldHookState`` directly — it calls methods on the context
    which delegate here.
    """

    __slots__ = (
        "stage", "has_diff", "warnings", "override_equal", "annotations",
    )

    def __init__(self) -> None:
        self.stage: HookStage | None = None
        self.has_diff: bool = False
        self.warnings: list[str] = []
        self.override_equal: bool = False
        self.annotations: list[str] = []

    def reset_for_stage(self, stage: HookStage, *, has_diff: bool) -> None:
        """Advance to the given stage; keep accumulated warnings.

        Warnings accumulate across stages (a VALIDATE warn and a
        REPORT warn both end up in ``DiffResult.warnings``).
        ``override_equal`` and ``annotations`` are per-stage scratch
        — the engine reads them after the stage completes and does
        not re-use the values in a later stage.
        """
        self.stage = stage
        self.has_diff = has_diff
        self.override_equal = False
        self.annotations = []


@dataclass(frozen=True)
class FieldHookContext:
    """Argument passed to a field-level hook.

    Either ``left_fd`` or ``right_fd`` may be ``None`` for
    one-sided visits (field only on the new or only on the old
    side). Likewise ``left_value`` / ``right_value`` may be
    ``None`` when the corresponding field is unset or absent.

    Repeated / map granularity: hooks fire **per element/entry**,
    not once per repeated/map field. ``ctx.left_value`` /
    ``ctx.right_value`` hold the individual scalar; the field
    descriptor (with ``is_repeated=True`` for repeated or a map
    entry's synthetic ``value`` sub-field for maps) is still in
    ``ctx.left_fd`` / ``ctx.right_fd``. Field-wide constraints
    that span the whole list (e.g. "max items") belong on a
    message-level hook registered against the parent message
    rather than a field hook. For a map field, ``ctx.left_fd``
    is the synthetic ``MapEntry.value`` descriptor, so
    ``ctx.left_fd.containing_type`` is the MapEntry message, not
    the user's outer container — use ``ctx.left_msg`` to reach
    the container.

    Cross-schema presence asymmetry: when one side has
    ``has_presence == True`` and the other doesn't (e.g. proto2
    optional on one side, proto3 implicit on the other), the
    engine cannot tell unambiguously whether a proto2 side is
    unset because the other side has no presence to match. In
    that case both ``left_value`` and ``right_value`` reflect the
    actual protobuf values (defaults when unset). Hooks that need
    strict presence should read
    ``ctx.left_msg.HasField(ctx.left_fd.name)`` (or the right-side
    equivalent) themselves.

    Attributes:
        path: ``FieldPath`` to the field being compared.
        left_fd: Left-side ``FieldDescriptor``, or ``None`` if the
            field exists only on the right.
        right_fd: Right-side ``FieldDescriptor``, or ``None`` if
            the field exists only on the left.
        left_value: Left-side value. ``None`` when the field is
            absent or unset on the left (including repeated/map
            extras where the left side has fewer elements or
            lacks the key).
        right_value: Right-side value. ``None`` when absent or
            unset on the right.
        left_msg: Left-side parent message (the one that contains
            this field). ``None`` for one-sided visits where the
            left subtree is absent.
        right_msg: Right-side parent message. ``None`` for
            one-sided visits where the right subtree is absent.
        left_pool: Descriptor pool the left message was resolved
            from. Useful for looking up custom-option extensions
            via :func:`protokit.options.get_option_value`.
        right_pool: Descriptor pool the right message was resolved
            from. Differs from ``left_pool`` for cross-pool
            comparisons.
    """

    path: FieldPath
    left_fd: "proto_descriptor.FieldDescriptor | None"
    right_fd: "proto_descriptor.FieldDescriptor | None"
    left_value: object | None
    right_value: object | None
    left_msg: "Message | None"
    right_msg: "Message | None"
    left_pool: "descriptor_pool.DescriptorPool"
    right_pool: "descriptor_pool.DescriptorPool"
    # Engine-managed scratch; hook code touches this via methods only.
    _state: _FieldHookState = field(
        default_factory=_FieldHookState, compare=False, repr=False,
    )

    @property
    def stage(self) -> HookStage | None:
        """The pipeline stage the hook is currently firing in."""
        return self._state.stage

    @property
    def has_diff(self) -> bool:
        """True when the engine is about to emit a ``Difference``.

        Meaningful only during ``HookStage.REPORT``. Always False
        during ``VALIDATE`` and ``COMPARE``. Hooks typically guard
        ``ctx.annotate(...)`` on this flag, but ``annotate()``
        itself is also a no-op outside REPORT.
        """
        return self._state.has_diff

    def warn(self, message: str) -> None:
        """Record a warning. Appears in ``DiffResult.warnings``.

        Works in every stage — VALIDATE is the typical caller, but
        COMPARE and REPORT hooks can warn too (e.g. "comparison
        took longer than expected"). The warning's path is always
        the context's field path.
        """
        self._state.warnings.append(message)

    def override_equal(self) -> None:
        """Mark these two values as equal for the purpose of diffing.

        Only effective during ``HookStage.COMPARE``; no-op
        otherwise. When called, ``_values_equal`` is not invoked
        (or its result is discarded) and no ``MODIFIED``
        ``Difference`` is produced for this leaf.

        Has no effect on ``treat_as_map`` key matching — only on
        value comparison.
        """
        if self._state.stage is HookStage.COMPARE:
            self._state.override_equal = True

    def annotate(self, message: str) -> None:
        """Attach an annotation string to the ``Difference``.

        Only effective during ``HookStage.REPORT`` when
        ``has_diff`` is True; no-op otherwise. Multiple hooks can
        annotate a single ``Difference`` — the strings accumulate
        into the ``Difference.annotations`` tuple in registration
        order.
        """
        if self._state.stage is HookStage.REPORT and self._state.has_diff:
            self._state.annotations.append(message)


class _MessageHookState:
    """Engine-internal mutable scratch space for a ``MessageHookContext``."""

    __slots__ = ("warnings",)

    def __init__(self) -> None:
        self.warnings: list[str] = []


@dataclass(frozen=True)
class MessageHookContext:
    """Argument passed to a message-level hook.

    Fires once per visited message — at the top of the iterative
    traversal loop, before the message's fields are compared.
    Message hooks can only ``warn()``; they cannot override
    comparison or annotate diffs (which are per-field concerns).

    For one-sided visits (added or removed subtree) exactly one of
    ``left_msg`` / ``right_msg`` is ``None``. The hook must guard
    on this if it reads message state.

    Attributes:
        path: ``FieldPath`` to the message. Empty path for the
            top-level message passed to ``compare()``.
        left_msg: Left-side ``Message`` instance, or ``None`` for
            one-sided visits where the subtree is only on the
            right.
        right_msg: Right-side ``Message`` instance, or ``None`` for
            one-sided visits where the subtree is only on the left.
        left_pool: Descriptor pool the left message was resolved
            from. When ``left_msg`` is None, this is the same
            ``left_pool`` as ``right_pool`` (there is no distinct
            left pool for a purely-added subtree).
        right_pool: Descriptor pool the right message was resolved
            from. When ``right_msg`` is None, same as
            ``left_pool`` (purely-removed subtree).
    """

    path: FieldPath
    left_msg: "Message | None"
    right_msg: "Message | None"
    left_pool: "descriptor_pool.DescriptorPool"
    right_pool: "descriptor_pool.DescriptorPool"
    _state: _MessageHookState = field(
        default_factory=_MessageHookState, compare=False, repr=False,
    )

    def warn(self, message: str) -> None:
        """Record a warning. Appears in ``DiffResult.warnings`` with the context path."""
        self._state.warnings.append(message)


# Type aliases for registration.
FieldHook = Callable[[FieldHookContext], None]
MessageValidateHook = Callable[[MessageHookContext], None]
