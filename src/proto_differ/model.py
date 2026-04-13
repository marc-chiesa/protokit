"""Data model for protobuf message diffs.

Pure data structures with zero protobuf imports. All descriptor-aware logic
lives in differ.py.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterator


class ChangeType(Enum):
    """Type of difference between two protobuf messages."""

    ADDED = "ADDED"
    REMOVED = "REMOVED"
    MODIFIED = "MODIFIED"
    TYPE_CHANGED = "TYPE_CHANGED"
    FIELD_NUMBER_CHANGED = "FIELD_NUMBER_CHANGED"
    CARDINALITY_CHANGED = "CARDINALITY_CHANGED"


@dataclass(frozen=True)
class EnumValue:
    """Represents a protobuf enum value with both name and number."""

    name: str
    number: int

    def __str__(self) -> str:
        return f"{self.name}({self.number})"


@dataclass(frozen=True)
class Warning:
    """A non-diff diagnostic message."""

    path: str | None
    message: str

    def __str__(self) -> str:
        if self.path:
            return f"{self.path}: {self.message}"
        return self.message


class DuplicateKeyError(ValueError):
    """Raised when treat_as_map encounters duplicate keys in a repeated field."""


class MissingKeyError(ValueError):
    """Raised when treat_as_map encounters a missing key field (proto2/proto3 optional)."""


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
    """A single segment of a field path: name + optional bracket."""

    name: str
    bracket: str | None = None  # raw bracket content, e.g. '2', '"env"', 'id=42'

    def __str__(self) -> str:
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
    """A parsed protobuf field path."""

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
        return ".".join(str(seg) for seg in self.segments)

    def __bool__(self) -> bool:
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
    """A single difference between two protobuf messages."""

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

    def __str__(self) -> str:
        path_str = str(self.path) if self.path else "(root)"
        match self.change_type:
            case ChangeType.ADDED:
                return f"+ {path_str}: {self.new_value}"
            case ChangeType.REMOVED:
                return f"- {path_str}: {self.old_value}"
            case ChangeType.MODIFIED:
                return f"~ {path_str}: {self.old_value} -> {self.new_value}"
            case ChangeType.TYPE_CHANGED:
                return f"T {path_str}: {self.left_type} -> {self.right_type}"
            case ChangeType.FIELD_NUMBER_CHANGED:
                return f"# {path_str}: field {self.left_field_number} -> {self.right_field_number}"
            case ChangeType.CARDINALITY_CHANGED:
                return f"C {path_str}: {self.left_label} -> {self.right_label}"
            case _:
                return f"? {path_str}: {self.change_type.value}"


@dataclass(frozen=True)
class DiffResult:
    """Immutable, filterable collection of differences.

    All filter methods return a new DiffResult instance.
    """

    differences: tuple[Difference, ...]
    warnings: tuple[Warning, ...] = ()
    truncated_paths: tuple[FieldPath, ...] = ()

    @property
    def is_complete(self) -> bool:
        """True if no subtrees were truncated by max_depth."""
        return not self.truncated_paths

    def has_changes(self) -> bool:
        """True if any differences were found.

        Returns:
            True when the result contains at least one Difference.
        """
        return bool(self.differences)

    def field_paths(self) -> list[FieldPath]:
        """List of all changed field paths.

        Returns:
            A list of FieldPath objects, one per difference.
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
        return len(self.differences)

    def __iter__(self) -> Iterator[Difference]:
        return iter(self.differences)

    def __bool__(self) -> bool:
        return self.has_changes()
