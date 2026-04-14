"""Data model for schema compatibility checking.

Pure data — enums, dataclasses, no traversal or rule logic. Rule and
profile modules depend on this, not the other way around, so keep this
module free of descriptor traversal or filtering logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterator

from protokit.message.model import FieldPath, Warning


class Severity(Enum):
    """How serious a compatibility finding is.

    Profiles include findings up to and including a severity threshold;
    see ``protokit.schema.profiles.LEVEL_SEVERITIES`` for the mapping.

    Members:
        WIRE: Deserialization will break (bytes on the wire cannot be
            decoded by the other schema version).
        SEMANTIC: Deserialization succeeds but the meaning of the data
            changes (e.g., a removed field, an added enum value).
        POLICY: An organization-defined rule was violated (e.g., a
            custom option was removed). No wire or semantic guarantee
            is broken.
    """

    WIRE = "WIRE"
    SEMANTIC = "SEMANTIC"
    POLICY = "POLICY"


class Direction(Enum):
    """Which direction of compatibility a finding threatens.

    Directions are framed by **which reader gets hurt**, not by which
    side of the schema changed. This keeps profile names (CONSUMER_SAFE
    / PRODUCER_SAFE) aligned with what they actually filter.

    Terminology mirrors common usage:

    - "Forward compatible" (old software reads new data) is preserved
      when no ``BACKWARD`` findings fire.
    - "Backward compatible" (new software reads old data) is preserved
      when no ``FORWARD`` findings fire.

    Members:
        FORWARD: Breaks backward compatibility — the new consumer
            fails (or misinterprets) old data. Fires for changes like
            ``enum_value_removed`` (new consumer sees a value it
            doesn't know) and ``required_field_added`` (old producer
            doesn't set the required field).
        BACKWARD: Breaks forward compatibility — the old consumer
            fails (or misinterprets) new data. Fires for changes like
            ``field_removed``, ``field_added``, ``enum_value_added``,
            and ``oneof_field_added`` — all of which make data
            produced under the new schema harder for the old consumer
            to interpret.
        BOTH: Breaks in both directions — typically wire-format breaks
            such as a field number reuse or a cross-wire-group type
            change.
    """

    FORWARD = "FORWARD"
    BACKWARD = "BACKWARD"
    BOTH = "BOTH"


class Verdict(Enum):
    """Top-level verdict for a compatibility check.

    Members:
        COMPATIBLE: No findings survived the profile filter.
        INCOMPATIBLE: At least one finding survived.
        UNKNOWN: Reserved — used by callers that cannot run the check
            to completion (currently unused by the built-in engine,
            which raises instead).
    """

    COMPATIBLE = "COMPATIBLE"
    INCOMPATIBLE = "INCOMPATIBLE"
    UNKNOWN = "UNKNOWN"


class CompatibilityLevel(Enum):
    """Named compatibility profile.

    A profile is a pair of filters — a severity threshold and a
    direction filter — applied to the raw findings emitted by rules.
    See ``protokit.schema.profiles`` for the filter logic.

    Members:
        WIRE: Only wire-format breaks, in any direction. Answers
            "will deserialization crash?"
        CONSUMER_SAFE: Wire + semantic findings in BACKWARD or BOTH
            direction. Answers "can old consumers safely read new
            messages?"
        PRODUCER_SAFE: Wire + semantic findings in FORWARD or BOTH
            direction. Answers "can new consumers safely read old
            messages?"
        STRICT: Every finding regardless of severity or direction,
            including POLICY. Answers "any compatibility concern at all?"
    """

    WIRE = "WIRE"
    CONSUMER_SAFE = "CONSUMER_SAFE"
    PRODUCER_SAFE = "PRODUCER_SAFE"
    STRICT = "STRICT"


@dataclass(frozen=True)
class Finding:
    """A single schema-compatibility finding.

    Emitted by a rule when it detects a difference between the old
    and new schema that matters at the rule's severity and direction.
    Findings are immutable; the engine collects them in a
    ``CompatibilityReport`` after applying profile filters.

    Either ``old_descriptor`` or ``new_descriptor`` may be ``None`` —
    for example, ``field_added`` has no old descriptor and
    ``field_removed`` has no new descriptor.

    Attributes:
        path: Dotted ``FieldPath`` to the schema element this finding
            describes (a field, enum value, or message).
        rule_id: Identifier of the rule that produced the finding,
            e.g. ``"field_removed"`` or a custom plugin's id.
        severity: WIRE / SEMANTIC / POLICY classification, used by
            profile filters and severity buckets on the report.
        direction: FORWARD / BACKWARD / BOTH classification, used by
            profile direction filters.
        message: Human-readable explanation of the finding, suitable
            for CLI or log output.
        old_descriptor: The relevant descriptor from the old schema
            (FieldDescriptor, EnumDescriptor, EnumValueDescriptor, or
            Descriptor depending on rule scope). ``None`` if the
            element exists only in the new schema.
        new_descriptor: The relevant descriptor from the new schema.
            ``None`` if the element exists only in the old schema.
    """

    path: FieldPath
    rule_id: str
    severity: Severity
    direction: Direction
    message: str
    old_descriptor: object | None = None
    new_descriptor: object | None = None

    def __str__(self) -> str:
        """Return a single-line representation for human display.

        Format: ``[SEVERITY/DIRECTION] path: message (rule_id)``.
        Empty paths render as ``(root)``.

        Returns:
            A formatted summary string suitable for CLI output.
        """
        path_str = str(self.path) if self.path else "(root)"
        return (
            f"[{self.severity.value}/{self.direction.value}] "
            f"{path_str}: {self.message} ({self.rule_id})"
        )


@dataclass(frozen=True)
class CompatibilityReport:
    """Result of a compatibility check under a specific profile.

    The ``findings`` tuple has already been filtered by the profile's
    severity and direction rules — consumers should treat it as the
    final authoritative set and not re-filter. Use ``is_compatible``
    for the boolean verdict and the three ``*_breaks`` properties to
    bucket findings by severity.

    Attributes:
        level: The ``CompatibilityLevel`` profile that was applied to
            produce ``findings``. Round-trips into JSON output and is
            useful when reports from different profiles are mixed.
        findings: All findings that survived the profile filter,
            ordered as the checker emitted them (traversal order).
            Defaults to an empty tuple, in which case the report is
            ``COMPATIBLE``.
        warnings: Non-finding diagnostics emitted during the check —
            primarily plugin-exception captures. Non-empty warnings
            mean the report may be incomplete (a plugin that was
            supposed to surface a finding failed). CI callers should
            treat a non-empty ``warnings`` tuple as an error condition
            and fail the check even if ``is_compatible`` is True —
            the ``protokit compat`` CLI does this automatically via
            exit code 2.
    """

    level: CompatibilityLevel
    findings: tuple[Finding, ...] = ()
    warnings: tuple[Warning, ...] = ()

    @property
    def is_compatible(self) -> bool:
        """Whether the report is free of any (post-filter) findings.

        Returns:
            True iff ``findings`` is empty.
        """
        return not self.findings

    @property
    def verdict(self) -> Verdict:
        """Compatibility verdict derived from the findings list.

        Returns:
            ``Verdict.COMPATIBLE`` if no findings, otherwise
            ``Verdict.INCOMPATIBLE``. ``Verdict.UNKNOWN`` is reserved
            for future use and is never returned by the built-in
            engine.
        """
        return Verdict.COMPATIBLE if self.is_compatible else Verdict.INCOMPATIBLE

    @property
    def wire_breaks(self) -> tuple[Finding, ...]:
        """All findings at ``Severity.WIRE``.

        Returns:
            A tuple containing the subset of ``findings`` whose
            severity is ``WIRE``, in original order.
        """
        return tuple(f for f in self.findings if f.severity is Severity.WIRE)

    @property
    def semantic_breaks(self) -> tuple[Finding, ...]:
        """All findings at ``Severity.SEMANTIC``.

        Returns:
            A tuple containing the subset of ``findings`` whose
            severity is ``SEMANTIC``, in original order.
        """
        return tuple(f for f in self.findings if f.severity is Severity.SEMANTIC)

    @property
    def policy_breaks(self) -> tuple[Finding, ...]:
        """All findings at ``Severity.POLICY``.

        Returns:
            A tuple containing the subset of ``findings`` whose
            severity is ``POLICY``, in original order.
        """
        return tuple(f for f in self.findings if f.severity is Severity.POLICY)

    def __len__(self) -> int:
        """Return the number of findings in the report.

        Returns:
            ``len(self.findings)``.
        """
        return len(self.findings)

    def __iter__(self) -> Iterator[Finding]:
        """Iterate over findings in original (traversal) order.

        Returns:
            An iterator over the findings tuple.
        """
        return iter(self.findings)

    def __bool__(self) -> bool:
        """Truthiness reflects presence of findings.

        Returns:
            True iff there is at least one finding (i.e., the report
            is INCOMPATIBLE).
        """
        return bool(self.findings)
