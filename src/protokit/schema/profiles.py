"""Compatibility profiles and policy composition.

A *profile* (``CompatibilityLevel``) is a named pair of filters: a
severity threshold and a direction filter. ``filter_for_level()``
applies a profile to a flat list of findings.

A *policy* (``CompatibilityPolicy``) bundles a profile with custom
field rules and ignore paths so a checker can be configured once and
reused. Policies are immutable — registering rules at runtime instead
means using ``SchemaChecker`` directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Iterable, Sequence

from google.protobuf import descriptor_pool

from protokit.schema.model import (
    CompatibilityLevel,
    CompatibilityReport,
    Direction,
    Finding,
    Severity,
)

if TYPE_CHECKING:
    from protokit.schema.plugins import FieldPlugin, MessagePlugin


# ---------------------------------------------------------------------------
# Profile filter tables
# ---------------------------------------------------------------------------

#: Which severities each level surfaces. Keyed by ``CompatibilityLevel``;
#: each value is the frozenset of ``Severity`` members the level retains.
#: Higher-strictness profiles are supersets of lower ones.
LEVEL_SEVERITIES: dict[CompatibilityLevel, frozenset[Severity]] = {
    CompatibilityLevel.WIRE: frozenset({Severity.WIRE}),
    CompatibilityLevel.CONSUMER_SAFE: frozenset({Severity.WIRE, Severity.SEMANTIC}),
    CompatibilityLevel.PRODUCER_SAFE: frozenset({Severity.WIRE, Severity.SEMANTIC}),
    CompatibilityLevel.STRICT: frozenset(
        {Severity.WIRE, Severity.SEMANTIC, Severity.POLICY}
    ),
}

#: Which directions each level cares about. ``BOTH`` is always relevant;
#: ``BACKWARD`` matters when protecting old consumers; ``FORWARD`` matters
#: when protecting against old producers.
LEVEL_DIRECTIONS: dict[CompatibilityLevel, frozenset[Direction]] = {
    CompatibilityLevel.WIRE: frozenset(
        {Direction.BOTH, Direction.BACKWARD, Direction.FORWARD}
    ),
    CompatibilityLevel.CONSUMER_SAFE: frozenset({Direction.BOTH, Direction.BACKWARD}),
    CompatibilityLevel.PRODUCER_SAFE: frozenset({Direction.BOTH, Direction.FORWARD}),
    CompatibilityLevel.STRICT: frozenset(
        {Direction.BOTH, Direction.BACKWARD, Direction.FORWARD}
    ),
}


def filter_for_level(
    findings: Iterable[Finding],
    level: CompatibilityLevel,
) -> list[Finding]:
    """Apply a profile's severity and direction filter to a finding stream.

    A finding is kept iff its ``severity`` is in
    ``LEVEL_SEVERITIES[level]`` AND its ``direction`` is in
    ``LEVEL_DIRECTIONS[level]``. Order is preserved.

    Args:
        findings: Iterable of raw ``Finding`` objects, typically the
            unfiltered output of a checker traversal.
        level: The profile to apply. Determines which severities and
            directions survive.

    Returns:
        A new list containing only the findings that pass the
        profile's filter, in the original iteration order.

    Raises:
        KeyError: If ``level`` is not a recognised
            ``CompatibilityLevel``.
    """
    sev_keep = LEVEL_SEVERITIES[level]
    dir_keep = LEVEL_DIRECTIONS[level]
    return [
        f for f in findings
        if f.severity in sev_keep and f.direction in dir_keep
    ]


# ---------------------------------------------------------------------------
# CompatibilityPolicy
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CompatibilityPolicy:
    """Immutable bundle: profile + custom plugins + ignore paths.

    Construct once, use on multiple type pairs::

        policy = CompatibilityPolicy(
            base=CompatibilityLevel.CONSUMER_SAFE,
            custom_rules=[("acme_meta", acme_metadata_checker)],
            message_rules=[("require_docs", require_docs_checker)],
            ignore_paths=("debug",),
        )
        report = policy.check(old_pool, "pkg.User", new_pool, "pkg.User")

    For dynamic configuration (registering rules at runtime or mixing
    in rule packs), use ``SchemaChecker`` directly.

    Attributes:
        base: The ``CompatibilityLevel`` profile applied to the
            checker. Defaults to ``CompatibilityLevel.CONSUMER_SAFE``
            to match the CLI default — override per use case.
        custom_rules: Sequence of ``(rule_id, plugin_fn)`` pairs to
            register as emit-style field plugins. Empty by default.
            Each ``plugin_fn`` must satisfy the ``FieldPlugin``
            protocol: ``(FieldRuleContext) -> None``.
        message_rules: Sequence of ``(rule_id, plugin_fn)`` pairs to
            register as emit-style message-level plugins. Empty by
            default. Each ``plugin_fn`` must satisfy the
            ``MessagePlugin`` protocol:
            ``(MessageRuleContext) -> None``. Use for cross-field
            invariants, require-docs rules, or other concerns that
            span a message rather than targeting one field.
        ignore_paths: Sequence of dotted prefix strings whose findings
            are suppressed. ``"debug"`` matches both ``debug`` and any
            descendant such as ``debug.inner.value``. Empty by default.
    """

    base: CompatibilityLevel = CompatibilityLevel.CONSUMER_SAFE
    custom_rules: Sequence[tuple[str, "FieldPlugin"]] = field(default_factory=tuple)
    message_rules: Sequence[tuple[str, "MessagePlugin"]] = field(default_factory=tuple)
    ignore_paths: Sequence[str] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        """Freeze caller-supplied sequences into immutable tuples.

        The dataclass is ``frozen=True``, but callers can still pass
        a ``list`` for ``custom_rules`` / ``message_rules`` /
        ``ignore_paths`` and mutate it later to change policy
        behavior after construction. We snapshot into tuples here so
        the frozen guarantee is real.
        """
        object.__setattr__(self, "custom_rules", tuple(self.custom_rules))
        object.__setattr__(self, "message_rules", tuple(self.message_rules))
        object.__setattr__(self, "ignore_paths", tuple(self.ignore_paths))

    def check(
        self,
        old_pool: descriptor_pool.DescriptorPool,
        old_type: str,
        new_pool: descriptor_pool.DescriptorPool,
        new_type: str,
    ) -> CompatibilityReport:
        """Run the configured checker on a type pair and return the report.

        Builds a fresh ``SchemaChecker`` for each call (policies are
        immutable). The same policy can be reused safely across many
        type comparisons.

        Args:
            old_pool: Descriptor pool containing the old schema.
            old_type: Fully-qualified message type name in ``old_pool``
                (e.g. ``"acme.User"``).
            new_pool: Descriptor pool containing the new schema.
            new_type: Fully-qualified message type name in ``new_pool``.
                May differ from ``old_type`` for cross-type comparisons.

        Returns:
            A ``CompatibilityReport`` with findings filtered by the
            policy's ``base`` level and pruned by ``ignore_paths``.

        Raises:
            ValueError: If either type name cannot be resolved in its
                pool. Propagated from ``SchemaChecker.check``.
            ValueError: If any ``ignore_paths`` entry is empty or is
                not a parseable dotted path. Propagated from
                :meth:`SchemaChecker.ignore`, and raised here rather
                than at construction — a policy carrying an empty
                entry builds successfully and fails on first use. An
                empty entry is rejected because it parses to the root
                path, which prefix-matches every finding and would
                silently suppress the whole report.
        """
        # Imported here to avoid a circular import at module load.
        from protokit.schema.checker import SchemaChecker

        checker = SchemaChecker(level=self.base)
        for rule_id, plugin_fn in self.custom_rules:
            checker.register_field_rule(rule_id, plugin_fn)
        for rule_id, plugin_fn in self.message_rules:
            checker.register_message_rule(rule_id, plugin_fn)
        for path in self.ignore_paths:
            checker.ignore(path)
        return checker.check(old_pool, old_type, new_pool, new_type)
