"""Lint-side type system for protokit schema lint (D1 foundation).

Defines the dataclasses, enums, and exception types that every
lint-side delivery (engine, registry, CLI formatters) load-bears on.
This module is import-safe to load on its own — it has zero runtime
imports of ``protokit.schema.compile`` (the ``LintCompileDiagnostic``
reference on ``LintReport.diagnostics`` is a string forward reference,
which keeps the cold-import contract intact: ``import protokit.schema``
must not pull in ``protokit.schema.lint`` or ``protokit.schema.compile``).

Types defined here, in declaration order:

1. ``EmitFn`` — ``Callable[[LintFinding], None]`` typedef.
2. ``LintSeverity`` — three-level severity ladder (info/warning/error).
3. ``ElementKind`` — eight protobuf-element kinds a rule can target.
4. Eight ``LintLocation`` variants (file / service / method / enum /
   enum-value / message / field / oneof) plus the ``LintLocation``
   union alias. Each variant has a stable ``__str__`` so log lines
   and JSON output share a single canonical address shape.
5. ``LintFinding`` — single rule violation. NO ``message`` field;
   formatters render from ``LintRuleSpec.message_template`` at output
   time (per S3-1C).
6. ``LintReport`` — top-level result bundle (findings + compile
   diagnostics + which profiles/rules ran). ``diagnostics`` is a
   string forward reference to ``LintCompileDiagnostic`` defined in
   ``protokit.schema.compile`` (Unit 3).
7. ``LintProfile`` — bundle of ``rule_ids`` + min severity + per-rule
   severity overrides. ``compose()`` merges multiple profiles using
   most-strict-wins semantics.
8. ``LintRuleSpec`` — registration record for a rule (id, severity,
   profiles, element kind, message template, callable).
   ``severity_for(violation_kind)`` resolves the right severity for
   multi-kind rules.
9. ``_LintContextEmitMixin`` — non-dataclass mixin that supplies
   ``emit()`` to all eight context dataclasses; constructs a
   ``LintFinding`` and dispatches to the engine-injected ``_emit_fn``.
10. Eight frozen lint-context dataclasses — one per ``ElementKind``.
    Each declares engine-injected fields (``_emit_fn``, ``_rule_id``,
    ``_effective_severity``) LAST and overrides ``location()`` to
    return the matching ``LintLocation`` variant.
11. ``DuplicateRuleError`` — raised when two rules try to register
    under the same ``rule_id``; carries both source locations in
    its message.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from types import ModuleType
from typing import TYPE_CHECKING, Any, Literal

from google.protobuf import descriptor as proto_descriptor
from google.protobuf import descriptor_pool

if TYPE_CHECKING:
    # TYPE_CHECKING is False at runtime, so this import is invisible
    # to ``import protokit.schema.lint.model`` and preserves the
    # cold-import contract for ``protokit compat`` (compile.py is not
    # transitively loaded). Without this import, ``LintReport.diagnostics``
    # is a string forward ref to ``LintCompileDiagnostic`` that
    # ``typing.get_type_hints(LintReport)`` cannot resolve — breaking
    # downstream tooling (Sphinx autodoc with autodoc_typehints,
    # JSON-schema generators, pydantic adapters, mypy plugins).
    from protokit.schema.compile import LintCompileDiagnostic

# Engine-injected closure that records a ``LintFinding`` into the
# in-flight report. Rule plugins call ``ctx.emit(...)`` on their lint
# context, which fills in ``rule_id``, ``severity``, and ``location``
# before dispatching here.
EmitFn = Callable[["LintFinding"], None]


class LintSeverity(Enum):
    """Severity ladder for lint findings.

    Ordering (least to most severe) is encoded by the
    ``_SEVERITY_RANK`` table below for ``LintProfile.compose()``
    most-strict-wins semantics. The string values match the values
    used by ``LintCompileDiagnostic.level`` so formatters can render
    findings and diagnostics through the same code path.
    """

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class ElementKind(Enum):
    """Protobuf element kinds a lint rule can target.

    A rule declares its element kind at registration time so the
    engine knows which descriptor walk to invoke it from. The eight
    kinds match the eight ``LintLocation`` / lint-context variants.
    """

    FILE = "file"
    SERVICE = "service"
    METHOD = "method"
    ENUM = "enum"
    ENUM_VALUE = "enum_value"
    MESSAGE = "message"
    FIELD = "field"
    ONEOF = "oneof"


# Ordering table for ``LintProfile.compose()`` most-strict-wins
# semantics. Higher number == more strict. ``Enum.value`` lexical
# ordering ("error" < "info" < "warning") would be wrong, so we use
# this explicit mapping instead.
_SEVERITY_RANK: dict[LintSeverity, int] = {
    LintSeverity.INFO: 0,
    LintSeverity.WARNING: 1,
    LintSeverity.ERROR: 2,
}


@dataclass(frozen=True)
class FileLocation:
    """Address of a finding at file scope.

    Attributes:
        file: Proto file name as recorded in the descriptor pool
            (e.g., ``"acme/user.proto"``).
    """

    file: str

    def __str__(self) -> str:
        """Render as ``file`` (e.g., ``"acme/user.proto"``)."""
        return self.file


@dataclass(frozen=True)
class ServiceLocation:
    """Address of a finding at service scope.

    Attributes:
        file: Proto file name (e.g., ``"acme/user.proto"``).
        service: Fully-qualified service name (e.g.,
            ``"acme.UserService"``).
    """

    file: str
    service: str

    def __str__(self) -> str:
        """Render as ``file:service`` (e.g., ``"acme/user.proto:acme.UserService"``)."""
        return f"{self.file}:{self.service}"


@dataclass(frozen=True)
class MethodLocation:
    """Address of a finding at method scope.

    Attributes:
        file: Proto file name.
        service: Fully-qualified service name.
        method: Method name (not fully qualified — the service
            already provides the namespace).
    """

    file: str
    service: str
    method: str

    def __str__(self) -> str:
        """Render as ``file:service/method`` (e.g., ``"a.proto:acme.S/GetUser"``)."""
        return f"{self.file}:{self.service}/{self.method}"


@dataclass(frozen=True)
class EnumLocation:
    """Address of a finding at enum scope.

    Attributes:
        file: Proto file name.
        enum: Fully-qualified enum name (e.g., ``"acme.Status"``).
    """

    file: str
    enum: str

    def __str__(self) -> str:
        """Render as ``file:enum`` (e.g., ``"a.proto:acme.Status"``)."""
        return f"{self.file}:{self.enum}"


@dataclass(frozen=True)
class EnumValueLocation:
    """Address of a finding at enum-value scope.

    Attributes:
        file: Proto file name.
        enum: Fully-qualified enum name.
        value: Enum value name (e.g., ``"ACTIVE"``).
    """

    file: str
    enum: str
    value: str

    def __str__(self) -> str:
        """Render as ``file:enum.value`` (e.g., ``"a.proto:acme.Status.ACTIVE"``)."""
        return f"{self.file}:{self.enum}.{self.value}"


@dataclass(frozen=True)
class MessageLocation:
    """Address of a finding at message scope.

    Attributes:
        file: Proto file name.
        message: Fully-qualified message name (e.g., ``"acme.User"``).
    """

    file: str
    message: str

    def __str__(self) -> str:
        """Render as ``file:message`` (e.g., ``"a.proto:acme.User"``)."""
        return f"{self.file}:{self.message}"


@dataclass(frozen=True)
class FieldLocation:
    """Address of a finding at field scope.

    Attributes:
        file: Proto file name.
        message: Fully-qualified parent message name.
        field: Field name (not fully qualified — the message already
            provides the namespace).
    """

    file: str
    message: str
    field: str

    def __str__(self) -> str:
        """Render as ``file:message.field`` (e.g., ``"a.proto:acme.User.email"``)."""
        return f"{self.file}:{self.message}.{self.field}"


@dataclass(frozen=True)
class OneofLocation:
    """Address of a finding at oneof scope.

    The ``#`` separator (instead of ``.``) distinguishes oneofs from
    fields under the same parent message in stringified output.

    Attributes:
        file: Proto file name.
        message: Fully-qualified parent message name.
        oneof: Oneof name.
    """

    file: str
    message: str
    oneof: str

    def __str__(self) -> str:
        """Render as ``file:message#oneof`` (e.g., ``"a.proto:acme.User#contact"``)."""
        return f"{self.file}:{self.message}#{self.oneof}"


# Discriminated union of all eight location variants. Functions that
# accept "any location" should use this alias; pattern-matching on
# specific variants is encouraged at consumer sites.
#
# Exhaustiveness contract (load-bearing for D2+):
#
# Adding a 9th variant in a future delivery silently breaks any
# ``match`` statement over ``LintLocation`` that lacks a wildcard arm.
# Consumers MUST end every match with::
#
#     case _:
#         typing.assert_never(loc)
#
# so a type-checker fails closed when a new variant is added (a
# ``case _: pass`` arm would silently accept the new variant). The
# project's mypy config (``strict = true``) catches missing
# ``assert_never`` arms when this convention is followed.
LintLocation = (
    FileLocation
    | ServiceLocation
    | MethodLocation
    | EnumLocation
    | EnumValueLocation
    | MessageLocation
    | FieldLocation
    | OneofLocation
)


@dataclass(frozen=True)
class LintFinding:
    """A single rule violation produced by a lint pass.

    Carries no human-readable ``message`` field by design (per S3-1C):
    formatters render the message at output time from
    ``LintRuleSpec.message_template`` interpolated with ``params``.
    Keeping templates centralized in the rule spec means a CLI tweak
    to copy doesn't require regenerating cached findings.

    Attributes:
        rule_id: The id under which the rule was registered (e.g.,
            ``"naming/snake-case-fields"``).
        severity: Effective severity for THIS finding — already
            resolved against profile overrides and the rule's own
            ``severity_for(violation_kind)``.
        location: Address of the violation. One of the eight
            ``LintLocation`` variants; choose by inspecting
            ``violation_kind`` or ``rule_id``.
        violation_kind: Sub-type discriminator for multi-kind rules.
            For single-kind rules this is typically the rule's only
            kind label; for multi-kind rules it selects which template
            and severity entry the formatter should pick.
        params: Free-form interpolation values for the rule's
            ``message_template``. Defaults to an empty dict.
    """

    rule_id: str
    severity: LintSeverity
    location: LintLocation
    violation_kind: str
    params: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Snapshot the caller-supplied ``params`` dict.

        ``frozen=True`` only prevents attribute REBINDING; nested
        mutation of a passed-in dict would still mutate the finding's
        params after construction. A rule plugin that reuses one
        params dict across multiple emits would otherwise produce
        findings whose params alias to the LAST set of values. Snapshot
        via ``dict(...)`` so each finding owns its params.
        """
        object.__setattr__(self, "params", dict(self.params))


@dataclass(frozen=True)
class LintRuntimeWarning:
    """Engine-stage warning recorded during a lint run.

    Two structurally distinct events share this type via the
    ``category`` discriminator (mirrors ``LintCompileDiagnostic``'s
    ``category: Literal[...]`` pattern in
    ``protokit.schema.compile``):

    1. ``"rule_exception"`` — a registered rule callable raised an
       exception that the engine caught (narrow catch tuple
       documented in ``LintEngine``). Carries ``exception_type`` (the
       caught exception's class name) and ``descriptor_path`` (a
       stable string locating the descriptor at which the rule was
       firing).
    2. ``"unloaded_rule"`` — the active profile's ``rule_ids``
       referenced a ``rule_id`` not loaded into the engine. Computed
       once at the start of ``LintEngine.run`` (set difference of
       ``profile.rule_ids`` against the engine's loaded
       ``rule_id``s); produces exactly one warning per missing
       ``rule_id``. Carries no exception or descriptor context;
       ``exception_type`` and ``descriptor_path`` are ``None``.

    **Field-population per category** (enforced by tests, not by the
    type system):

    +-------------------+--------------------+--------------------+
    | Field             | ``rule_exception`` | ``unloaded_rule``  |
    +===================+====================+====================+
    | ``category``      | ``"rule_exception"`` | ``"unloaded_rule"`` |
    | ``rule_id``       | populated          | populated          |
    | ``message``       | ``str(exc)``       | human-readable     |
    | ``exception_type``| exception class name | ``None``         |
    | ``descriptor_path``| see table below   | ``None``           |
    +-------------------+--------------------+--------------------+

    For ``category="rule_exception"``, ``descriptor_path`` mirrors
    D1's ``LintLocation.__str__`` shapes per ``ElementKind``:

    +--------------+---------------------------------------+
    | ElementKind  | ``descriptor_path`` format            |
    +==============+=======================================+
    | FILE         | ``"file.proto"``                      |
    | SERVICE      | ``"file.proto:full.Service"``         |
    | METHOD       | ``"file.proto:full.Service/method"``  |
    | ENUM         | ``"file.proto:full.Enum"``            |
    | ENUM_VALUE   | ``"file.proto:full.Enum.VALUE"``      |
    | MESSAGE      | ``"file.proto:full.Message"``         |
    | FIELD        | ``"file.proto:full.Message.field"``   |
    | ONEOF        | ``"file.proto:full.Message#oneof"``   |
    +--------------+---------------------------------------+

    **mypy-strict narrowing pattern.** mypy ``--strict`` does not
    narrow ``Optional`` fields by Literal discriminator within a
    single dataclass. Downstream consumers (D4 formatters) match D1's
    ``LintCompileDiagnostic`` precedent: branch on ``category``,
    then ``assert w.descriptor_path is not None`` (or use ``cast``)
    inside the ``"rule_exception"`` branch before reading. This is
    the same pattern ``LintCompileDiagnostic`` requires for its own
    Optional fields (``command``, ``exit_code``, ``stderr``,
    ``exception_type``); D2 introduces no new convention.

    Attributes:
        category: Discriminator for the two event shapes.
        rule_id: The id of the rule the warning is about. For
            ``"unloaded_rule"`` this is the missing id; for
            ``"rule_exception"`` this is the rule that raised.
        message: Human-readable description. For
            ``"rule_exception"`` typically ``str(exc)``; for
            ``"unloaded_rule"`` an explanation that the id was named
            in a profile but not loaded.
        exception_type: ``__name__`` of the caught exception class
            for ``"rule_exception"``; ``None`` for ``"unloaded_rule"``.
        descriptor_path: Stable string locating the descriptor at
            which a ``"rule_exception"`` was firing (per the table
            above); ``None`` for ``"unloaded_rule"``.
    """

    category: Literal["rule_exception", "unloaded_rule"]
    rule_id: str
    message: str
    exception_type: str | None = None
    descriptor_path: str | None = None


@dataclass(frozen=True)
class LintReport:
    """Top-level result bundle for a lint pass.

    Holds the findings, any compile-stage diagnostics surfaced by the
    backend, and which profiles / rules participated. ``diagnostics``
    references ``LintCompileDiagnostic`` from
    ``protokit.schema.compile`` via a STRING forward reference — at
    runtime the class is just whatever the caller put in the tuple,
    so importing this module does NOT drag the compile module in.
    This keeps the cold-import contract: ``import protokit.schema``
    stays free of ``protokit.schema.lint`` and ``compile`` until the
    caller opts in.

    Attributes:
        findings: Tuple of all rule violations produced by the pass.
            Order is engine-defined (currently file order, then
            descriptor walk order). Defaults to ``()``.
        diagnostics: Tuple of compile-stage diagnostics from the
            backend (protoxy / protoc). May include ``info``-level
            fallback notes and ``error``-level failures. Defaults to
            ``()``.
        profiles_run: Tuple of profile names that the engine resolved
            and ran. Useful for audit logs / report headers. Defaults
            to ``()``.
        rules_run: Tuple of rule_ids that actually executed (after
            profile filtering). Defaults to ``()``.
        runtime_warnings: Tuple of engine-stage warnings raised during
            the run. Two categories share the type:
            ``"rule_exception"`` (a registered rule callable raised
            an exception caught by the engine's narrow catch tuple)
            and ``"unloaded_rule"`` (the active profile referenced a
            ``rule_id`` not loaded into the engine). Defaults to
            ``()``. See :class:`LintRuntimeWarning` for field-
            population rules per category.
        filtered_count: Count of findings dropped at emit time
            because their effective severity ranked below the active
            profile's ``min_severity``. Lets D3+ tooling render
            ``--statistics`` / ``--max-warnings`` flows without
            re-walking at a lower threshold. Defaults to ``0``.
    """

    findings: tuple[LintFinding, ...] = ()
    diagnostics: tuple[LintCompileDiagnostic, ...] = ()
    profiles_run: tuple[str, ...] = ()
    rules_run: tuple[str, ...] = ()
    runtime_warnings: tuple[LintRuntimeWarning, ...] = ()
    filtered_count: int = 0

    def __post_init__(self) -> None:
        """Snapshot caller-supplied sequences into immutable tuples.

        The dataclass is ``frozen=True``, but a caller can still pass
        a ``list`` and mutate it later to alter what looks like an
        immutable report. Mirrors
        ``schema/profiles.py:CompatibilityPolicy.__post_init__``.
        """
        object.__setattr__(self, "findings", tuple(self.findings))
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))
        object.__setattr__(self, "profiles_run", tuple(self.profiles_run))
        object.__setattr__(self, "rules_run", tuple(self.rules_run))
        object.__setattr__(
            self, "runtime_warnings", tuple(self.runtime_warnings),
        )


@dataclass(frozen=True)
class LintProfile:
    """Bundle of rule_ids + severity policy.

    A profile says "run this set of rules at (at least) this severity,
    with these per-rule overrides." Multiple profiles can be composed
    via :meth:`compose` with most-strict-wins semantics.

    Attributes:
        name: Short human-readable identifier (e.g., ``"default"``,
            ``"strict"``, ``"composed"``).
        rule_ids: Set of rule ids the profile activates. Defaults to
            an empty frozenset.
        min_severity: Lowest severity that survives filtering — any
            finding with rank lower than this is dropped before the
            report is returned. Defaults to ``LintSeverity.WARNING``.
        rule_severity_overrides: Per-rule severity ceilings. Maps
            ``rule_id`` to the severity the rule should fire at when
            this profile is active, regardless of the rule's default.
            Defaults to an empty dict.
    """

    name: str
    rule_ids: frozenset[str] = frozenset()
    min_severity: LintSeverity = LintSeverity.WARNING
    rule_severity_overrides: dict[str, LintSeverity] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Snapshot caller-supplied dict so the frozen guarantee is real.

        Same rationale as :class:`LintFinding` and :class:`LintReport`:
        ``frozen=True`` does not prevent nested mutation of a passed-in
        dict. Profiles passed across deliveries / plugin boundaries
        could otherwise be mutated post-construction and corrupt the
        composition.
        """
        object.__setattr__(
            self, "rule_severity_overrides", dict(self.rule_severity_overrides),
        )

    @classmethod
    def compose(cls, *profiles: LintProfile) -> LintProfile:
        """Merge zero or more profiles into a single composed profile.

        Composition rules:

        - Zero arguments returns the identity profile
          (``LintProfile(name="composed")``).
        - A single ``LintProfile`` argument returns that profile
          unchanged.
        - Multiple arguments union ``rule_ids``, take the strictest
          ``min_severity``, and merge ``rule_severity_overrides`` with
          most-strict-wins on conflicts.

        Profile-name resolution is the caller's responsibility (the
        engine resolves names against its registry before calling
        ``compose``); this method is pure and side-effect-free.

        Args:
            *profiles: ``LintProfile`` instances to merge.

        Returns:
            A new ``LintProfile`` named ``"composed"`` (single-arg
            case returns the input as-is, preserving its name).

        Raises:
            TypeError: If any argument is not a ``LintProfile``
                instance — including ``str`` (caller must resolve
                names) and ``None`` (guard against forwarded registry
                misses).
        """
        for prof in profiles:
            if not isinstance(prof, LintProfile):
                raise TypeError(
                    f"compose() requires LintProfile instances; got "
                    f"{type(prof).__name__}: {prof!r}. Profile-name "
                    f"resolution is the caller's responsibility."
                )

        if not profiles:
            return cls(name="composed")
        if len(profiles) == 1:
            return profiles[0]

        merged_rule_ids: frozenset[str] = frozenset().union(
            *(p.rule_ids for p in profiles)
        )

        # Strictest min_severity = highest rank in _SEVERITY_RANK.
        merged_min_severity: LintSeverity = max(
            (p.min_severity for p in profiles),
            key=lambda s: _SEVERITY_RANK[s],
        )

        merged_overrides: dict[str, LintSeverity] = {}
        for prof in profiles:
            for rule_id, sev in prof.rule_severity_overrides.items():
                existing = merged_overrides.get(rule_id)
                if existing is None or _SEVERITY_RANK[sev] > _SEVERITY_RANK[existing]:
                    merged_overrides[rule_id] = sev

        return cls(
            name="composed",
            rule_ids=merged_rule_ids,
            min_severity=merged_min_severity,
            rule_severity_overrides=merged_overrides,
        )

    @classmethod
    def from_pack(
        cls, module: ModuleType, profile_name: str,
    ) -> LintProfile:
        """Derive a profile from a rule pack module's declared membership.

        Walks ``module.RULES`` (a tuple of ``@lint_rule``-decorated
        functions, by convention echoing compat's
        ``schema/checker.py:217-235`` pattern), reads each function's
        ``_lint_spec`` attribute, and selects the rule_ids whose
        ``LintRuleSpec.profiles`` tuple includes ``profile_name``.

        This makes ``LintRuleSpec.profiles`` load-bearing for end
        users: rule pack authors annotate profile membership at the
        rule (``@lint_rule(..., profiles=("default",))``), and
        callers derive the profile via this classmethod. D5's
        ``[tool.protokit.lint] profile = "default"`` resolves
        trivially via this method.

        Returns an empty-rule_ids profile when the module has no
        ``RULES`` attribute, when ``RULES`` is empty, or when no rule
        in the pack declares ``profile_name`` — matching the explicit
        empty-rule_ids contract (the engine then runs zero rules per
        the locked R12).

        Args:
            module: An imported module exposing ``RULES`` (a tuple of
                ``@lint_rule``-decorated functions). Falls back to
                ``()`` when the attribute is missing.
            profile_name: The profile name to filter by. Functions
                whose ``_lint_spec.profiles`` includes this string
                are selected; others are skipped.

        Returns:
            A new ``LintProfile`` with ``name=profile_name`` and
            ``rule_ids`` containing the matching rule_ids. The
            profile's ``min_severity`` and ``rule_severity_overrides``
            use their dataclass defaults; callers needing different
            policy should construct ``LintProfile`` directly or
            compose with another profile.

        Raises:
            AttributeError: If a function in ``module.RULES`` lacks a
                ``_lint_spec`` attribute (i.e., wasn't decorated with
                ``@lint_rule``). Surfaces author errors immediately
                rather than silently skipping.
        """
        rule_ids: list[str] = []
        for fn in getattr(module, "RULES", ()):
            spec = fn._lint_spec
            if profile_name in spec.profiles:
                rule_ids.append(spec.rule_id)
        return cls(name=profile_name, rule_ids=frozenset(rule_ids))


@dataclass(frozen=True)
class LintRuleSpec:
    """Registration record for a single lint rule.

    A rule may be single-kind (one ``severity`` + one
    ``message_template``) or multi-kind (a dict keyed by
    ``violation_kind`` for both fields). Multi-kind rules let one
    callable cover several closely related sub-violations without
    duplicating the engine wiring.

    Attributes:
        rule_id: Globally unique id (typically
            ``"<category>/<short-name>"``).
        severity: Default severity. Either a ``LintSeverity`` (single
            kind) or a dict mapping ``violation_kind`` ->
            ``LintSeverity`` (multi-kind).
        profiles: Tuple of profile names this rule belongs to. Used
            by the engine to decide whether to invoke the rule under
            a given composed profile.
        source_spec: Optional human-readable spec reference (e.g.,
            a URL or ``"AIP-122"``). Empty by default.
        element: Which descriptor element the rule visits. Defaults
            to ``ElementKind.FIELD`` since field-level rules are by
            far the most common.
        message_template: Format string (single kind) or dict mapping
            ``violation_kind`` -> format string (multi-kind). The
            engine interpolates ``LintFinding.params`` into this at
            render time.
        fn: The actual rule callable. ``None`` is permitted only for
            placeholder specs in tests; the engine rejects ``None``
            at registration time in production paths.
    """

    rule_id: str
    severity: LintSeverity | dict[str, LintSeverity]
    profiles: tuple[str, ...]
    source_spec: str = ""
    element: ElementKind = ElementKind.FIELD
    message_template: str | dict[str, str] = ""
    fn: Callable[..., None] | None = None

    def __post_init__(self) -> None:
        """Snapshot dict-shaped fields and enforce the dual-shape invariant.

        Two responsibilities:

        1. **Snapshot.** Multi-kind specs carry dicts that must not be
           mutated after registration — a registry-corrupting abuse
           case where ``severity_for(kind)`` would return different
           severities at different times. Single-kind variants
           (``LintSeverity`` / ``str``) pass through untouched.
        2. **Dual-shape pairing.** ``severity`` and ``message_template``
           must be the SAME shape: both single-kind (``LintSeverity`` +
           ``str``) or both multi-kind (``dict`` + ``dict``). Mixing
           shapes is rejected at registration time so plugin authors
           hit a clear failure rather than a runtime KeyError at first
           render.
        """
        severity = self.severity
        template = self.message_template
        severity_is_dict = isinstance(severity, dict)
        template_is_dict = isinstance(template, dict)
        if severity_is_dict != template_is_dict:
            raise TypeError(
                f"LintRuleSpec({self.rule_id!r}): severity and "
                f"message_template must share the same shape "
                f"(both single-kind, or both dict for multi-kind); "
                f"got severity={type(severity).__name__}, "
                f"message_template={type(template).__name__}."
            )
        if isinstance(severity, dict):
            object.__setattr__(self, "severity", dict(severity))
        if isinstance(template, dict):
            object.__setattr__(self, "message_template", dict(template))

    def severity_for(self, violation_kind: str) -> LintSeverity:
        """Return the effective default severity for ``violation_kind``.

        For single-kind rules (``self.severity`` is a
        ``LintSeverity``), the argument is ignored and the stored
        severity is returned. For multi-kind rules (``self.severity``
        is a dict), the kind is looked up in the dict; an unregistered
        kind raises ``KeyError`` so misconfigured calls fail loudly
        rather than silently emitting at a wrong severity.

        Args:
            violation_kind: Sub-type discriminator. For single-kind
                rules this can be any string (it is ignored).

        Returns:
            The default severity to assign to a finding of this
            kind. Profile overrides are applied later by the engine.

        Raises:
            KeyError: If ``self.severity`` is a dict and
                ``violation_kind`` is not a registered key.
        """
        if isinstance(self.severity, LintSeverity):
            return self.severity
        return self.severity[violation_kind]


class _LintContextEmitMixin:
    """Mixin supplying ``emit()`` to every lint context dataclass.

    NOT a dataclass itself. The eight concrete contexts inherit from
    this mixin AND declare engine-injected attributes
    (``_emit_fn``, ``_rule_id``, ``_effective_severity``) as their own
    dataclass fields — the mixin reads them via ``self`` but does not
    declare them, so dataclass field-ordering rules apply only to the
    concrete subclass.

    Subclasses MUST override :meth:`location` to return the correct
    ``LintLocation`` variant for their element kind.
    """

    # The engine-injected attributes live on the concrete dataclass;
    # the mixin only references them. Type-checkers see them as
    # attribute accesses, which is what we want — declaring them on
    # the mixin would force the dataclass field ordering and conflict
    # with the "engine-injected fields LAST" rule per pass-2 codex
    # correction.

    def emit(
        self,
        *,
        violation_kind: str,
        params: dict[str, Any] | None = None,
    ) -> None:
        """Record a lint finding at this context's location.

        Builds a ``LintFinding`` from this context's ``_rule_id``,
        the resolved severity for ``violation_kind`` (via
        ``_effective_severity``), this context's ``location()``, and
        the caller-supplied ``violation_kind`` / ``params``, then
        dispatches it to the engine's ``_emit_fn``.

        Args:
            violation_kind: Sub-type discriminator. For single-kind
                rules this is typically the rule's only kind label.
            params: Free-form interpolation values for the rule's
                ``message_template``. Defaults to an empty dict if
                ``None``.
        """
        finding = LintFinding(
            rule_id=self._rule_id,  # type: ignore[attr-defined]
            severity=self._effective_severity(violation_kind),  # type: ignore[attr-defined]
            location=self.location(),
            violation_kind=violation_kind,
            params=params or {},
        )
        self._emit_fn(finding)  # type: ignore[attr-defined]

    def location(self) -> LintLocation:
        """Return the ``LintLocation`` variant for this context.

        Subclasses MUST override this method.

        Returns:
            The matching ``LintLocation`` variant.

        Raises:
            NotImplementedError: Always, when called on the mixin
                directly or on a subclass that forgot to override.
        """
        raise NotImplementedError(
            "lint context subclasses must override location()"
        )


@dataclass(frozen=True)
class FileLintContext(_LintContextEmitMixin):
    """Lint context for file-level rules.

    Attributes:
        file: The proto file's descriptor.
        pool: Descriptor pool the file was resolved from. Useful for
            cross-file lookups (e.g., resolving imported types).
        profile: Name of the active profile (e.g., ``"default"``).
            Rules can branch on this for profile-specific behavior.
        _emit_fn: Engine-injected closure that records findings into
            the report. Use ``self.emit(...)`` instead of calling.
        _rule_id: Engine-injected rule_id stamped on every emitted
            finding.
        _effective_severity: Engine-injected resolver that maps a
            ``violation_kind`` to the effective ``LintSeverity`` for
            this rule under the active profile.
    """

    file: proto_descriptor.FileDescriptor
    pool: descriptor_pool.DescriptorPool
    profile: str
    _emit_fn: EmitFn
    _rule_id: str
    _effective_severity: Callable[[str], LintSeverity]

    def location(self) -> LintLocation:
        """Return ``FileLocation(file=self.file.name)``."""
        return FileLocation(file=self.file.name)


@dataclass(frozen=True)
class ServiceLintContext(_LintContextEmitMixin):
    """Lint context for service-level rules.

    Attributes:
        service: The service's descriptor.
        file: The parent file's descriptor.
        pool: Descriptor pool the service was resolved from.
        profile: Name of the active profile.
        _emit_fn: Engine-injected emit closure.
        _rule_id: Engine-injected rule_id.
        _effective_severity: Engine-injected severity resolver.
    """

    service: proto_descriptor.ServiceDescriptor
    file: proto_descriptor.FileDescriptor
    pool: descriptor_pool.DescriptorPool
    profile: str
    _emit_fn: EmitFn
    _rule_id: str
    _effective_severity: Callable[[str], LintSeverity]

    def location(self) -> LintLocation:
        """Return ``ServiceLocation(file, service.full_name)``."""
        return ServiceLocation(
            file=self.file.name,
            service=self.service.full_name,
        )


@dataclass(frozen=True)
class MethodLintContext(_LintContextEmitMixin):
    """Lint context for method-level rules.

    Attributes:
        method: The method's descriptor.
        service: The parent service's descriptor.
        file: The parent file's descriptor.
        pool: Descriptor pool the method was resolved from.
        profile: Name of the active profile.
        _emit_fn: Engine-injected emit closure.
        _rule_id: Engine-injected rule_id.
        _effective_severity: Engine-injected severity resolver.
    """

    method: proto_descriptor.MethodDescriptor
    service: proto_descriptor.ServiceDescriptor
    file: proto_descriptor.FileDescriptor
    pool: descriptor_pool.DescriptorPool
    profile: str
    _emit_fn: EmitFn
    _rule_id: str
    _effective_severity: Callable[[str], LintSeverity]

    def location(self) -> LintLocation:
        """Return ``MethodLocation(file, service.full_name, method.name)``."""
        return MethodLocation(
            file=self.file.name,
            service=self.service.full_name,
            method=self.method.name,
        )


@dataclass(frozen=True)
class EnumLintContext(_LintContextEmitMixin):
    """Lint context for enum-level rules.

    Attributes:
        enum: The enum's descriptor.
        file: The parent file's descriptor.
        pool: Descriptor pool the enum was resolved from.
        profile: Name of the active profile.
        _emit_fn: Engine-injected emit closure.
        _rule_id: Engine-injected rule_id.
        _effective_severity: Engine-injected severity resolver.
    """

    enum: proto_descriptor.EnumDescriptor
    file: proto_descriptor.FileDescriptor
    pool: descriptor_pool.DescriptorPool
    profile: str
    _emit_fn: EmitFn
    _rule_id: str
    _effective_severity: Callable[[str], LintSeverity]

    def location(self) -> LintLocation:
        """Return ``EnumLocation(file, enum.full_name)``."""
        return EnumLocation(
            file=self.file.name,
            enum=self.enum.full_name,
        )


@dataclass(frozen=True)
class EnumValueLintContext(_LintContextEmitMixin):
    """Lint context for enum-value rules.

    Attributes:
        value: The enum value's descriptor.
        enum: The parent enum's descriptor.
        file: The parent file's descriptor.
        pool: Descriptor pool the enum value was resolved from.
        profile: Name of the active profile.
        _emit_fn: Engine-injected emit closure.
        _rule_id: Engine-injected rule_id.
        _effective_severity: Engine-injected severity resolver.
    """

    value: proto_descriptor.EnumValueDescriptor
    enum: proto_descriptor.EnumDescriptor
    file: proto_descriptor.FileDescriptor
    pool: descriptor_pool.DescriptorPool
    profile: str
    _emit_fn: EmitFn
    _rule_id: str
    _effective_severity: Callable[[str], LintSeverity]

    def location(self) -> LintLocation:
        """Return ``EnumValueLocation(file, enum.full_name, value.name)``."""
        return EnumValueLocation(
            file=self.file.name,
            enum=self.enum.full_name,
            value=self.value.name,
        )


@dataclass(frozen=True)
class MessageLintContext(_LintContextEmitMixin):
    """Lint context for message-level rules.

    Attributes:
        message: The message's descriptor.
        file: The parent file's descriptor.
        pool: Descriptor pool the message was resolved from.
        profile: Name of the active profile.
        _emit_fn: Engine-injected emit closure.
        _rule_id: Engine-injected rule_id.
        _effective_severity: Engine-injected severity resolver.
    """

    message: proto_descriptor.Descriptor
    file: proto_descriptor.FileDescriptor
    pool: descriptor_pool.DescriptorPool
    profile: str
    _emit_fn: EmitFn
    _rule_id: str
    _effective_severity: Callable[[str], LintSeverity]

    def location(self) -> LintLocation:
        """Return ``MessageLocation(file, message.full_name)``."""
        return MessageLocation(
            file=self.file.name,
            message=self.message.full_name,
        )


@dataclass(frozen=True)
class FieldLintContext(_LintContextEmitMixin):
    """Lint context for field-level rules.

    Attributes:
        field: The field's descriptor.
        message: The parent message's descriptor.
        file: The parent file's descriptor.
        pool: Descriptor pool the field was resolved from.
        profile: Name of the active profile.
        _emit_fn: Engine-injected emit closure.
        _rule_id: Engine-injected rule_id.
        _effective_severity: Engine-injected severity resolver.
    """

    field: proto_descriptor.FieldDescriptor
    message: proto_descriptor.Descriptor
    file: proto_descriptor.FileDescriptor
    pool: descriptor_pool.DescriptorPool
    profile: str
    _emit_fn: EmitFn
    _rule_id: str
    _effective_severity: Callable[[str], LintSeverity]

    def location(self) -> LintLocation:
        """Return ``FieldLocation(file, message.full_name, field.name)``."""
        return FieldLocation(
            file=self.file.name,
            message=self.message.full_name,
            field=self.field.name,
        )


@dataclass(frozen=True)
class OneofLintContext(_LintContextEmitMixin):
    """Lint context for oneof-level rules.

    Attributes:
        oneof: The oneof's descriptor.
        message: The parent message's descriptor.
        file: The parent file's descriptor.
        pool: Descriptor pool the oneof was resolved from.
        profile: Name of the active profile.
        _emit_fn: Engine-injected emit closure.
        _rule_id: Engine-injected rule_id.
        _effective_severity: Engine-injected severity resolver.
    """

    oneof: proto_descriptor.OneofDescriptor
    message: proto_descriptor.Descriptor
    file: proto_descriptor.FileDescriptor
    pool: descriptor_pool.DescriptorPool
    profile: str
    _emit_fn: EmitFn
    _rule_id: str
    _effective_severity: Callable[[str], LintSeverity]

    def location(self) -> LintLocation:
        """Return ``OneofLocation(file, message.full_name, oneof.name)``."""
        return OneofLocation(
            file=self.file.name,
            message=self.message.full_name,
            oneof=self.oneof.name,
        )


class DuplicateRuleError(Exception):
    """Raised when two rules try to register under the same id.

    Carries both source locations (module + qualname of each
    callable) in its message so the operator can find the conflict
    quickly. The instance attributes (``rule_id``, ``first_fn``,
    ``second_fn``) are preserved for programmatic inspection by
    higher-level error handlers (e.g., the registry's bulk-load
    path).

    Attributes:
        rule_id: The duplicated id.
        first_fn: The callable that registered first under this id.
        second_fn: The callable that tried to register second.
    """

    def __init__(
        self,
        rule_id: str,
        first_fn: Callable[..., Any],
        second_fn: Callable[..., Any],
    ) -> None:
        """Construct the error with both source locations rendered.

        Args:
            rule_id: The duplicated rule id.
            first_fn: The original registrant.
            second_fn: The conflicting registrant.
        """
        self.rule_id = rule_id
        self.first_fn = first_fn
        self.second_fn = second_fn
        super().__init__(
            f"rule_id {rule_id!r} is already registered by "
            f"{first_fn.__module__}.{first_fn.__qualname__}; refusing to "
            f"override with {second_fn.__module__}.{second_fn.__qualname__}"
        )


class LintRuleError(Exception):
    """Explicit fail-soft signal a rule callable can raise.

    The ``LintEngine``'s rule-callable boundary catches a narrow set
    of exceptions and converts them to
    ``LintRuntimeWarning(category="rule_exception")`` while continuing
    the walk. ``LintRuleError`` is the documented signal a rule
    author uses to say "I detected a condition I want to surface as
    a warning, not as a finding, and I want the rest of the walk to
    proceed."

    The catch tuple is documented in the engine's source; at minimum
    it includes ``(SystemExit, ValueError, TypeError, KeyError,
    AttributeError, LookupError, LintRuleError)``.

    **Escape hatch for "abort the run".** Rule authors who want to
    halt the entire lint pass (e.g., catastrophic schema corruption
    detected; sentinel value indicating downstream rules cannot
    proceed) should raise an ``Exception`` subclass NOT in the
    engine's catch tuple — ``RuntimeError`` is the canonical pick.
    Such exceptions propagate uncaught, tearing down
    ``LintEngine.run`` and surfacing to the caller. Note that
    ``sys.exit()`` (and ``pytest.exit()``, which subclasses
    ``SystemExit``) are caught by the engine and converted to
    runtime warnings — a deliberate divergence from D1's R16 to
    prevent rules from silently terminating the calling process. See
    the D2 plan's Key Technical Decisions for the full rationale.

    No fields beyond ``Exception``'s; the engine reads
    ``str(exc)`` into ``LintRuntimeWarning.message`` and
    ``exc.__class__.__name__`` into ``exception_type``.
    """
