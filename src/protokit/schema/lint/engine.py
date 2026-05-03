"""``LintEngine`` — descriptor-tree walker + per-instance rule registry.

Mirrors compat's ``SchemaChecker`` per-instance pattern at
``schema/checker.py:136-143, 217-235``: each engine instance owns
its loaded-rule dict; there is no process-global registry.
``load_rule_pack(module: ModuleType)`` reads ``module.RULES``
(decorated by ``@lint_rule``), extracts each function's
``_lint_spec``, and registers per-instance with cross-pack
``DuplicateRuleError`` detection. ``run(compile_result, *, profile)``
walks ``compile_result.root_files`` in sorted order, dispatches
rules per ``ElementKind`` with a narrow exception-catch tuple
(including ``SystemExit`` per the D2-specific R16 amendment), and
returns a ``LintReport`` with findings, runtime warnings, and a
filtered-count for the min-severity gate.

Walk order is deterministic by construction: per-level
lexicographic sort by ``full_name`` (with file-`.name` tie-break
for ambiguous packages). Rule registration order within an
``ElementKind`` is preserved as the secondary order. The walk
order, severity-resolution rules, and failure-containment posture
are documented in ``docs/plans/2026-05-02-001-feat-protokit-lint-d2-engine-plan.md``.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING, Any, cast

from protokit.schema.lint.model import (
    _SEVERITY_RANK,
    DuplicateRuleError,
    ElementKind,
    EnumLintContext,
    EnumValueLintContext,
    FieldLintContext,
    FileLintContext,
    LintFinding,
    LintProfile,
    LintReport,
    LintRuleError,
    LintRuleSpec,
    LintRuntimeWarning,
    LintSeverity,
    MessageLintContext,
    MethodLintContext,
    OneofLintContext,
    ServiceLintContext,
)

if TYPE_CHECKING:
    from types import ModuleType

    from google.protobuf import descriptor as proto_descriptor

    from protokit.schema.compile import CompileResult


# Engine-stage exception tuple. Catching ``SystemExit`` is a deliberate
# divergence from D1's R16 wording: ``LintEngine.run`` is a library call
# that returns a ``LintReport``; a rule calling ``sys.exit(0)`` must NOT
# silently terminate the caller's process and produce zero findings. See
# the D2 plan's Key Technical Decisions for the standalone rationale
# (independent of the formatter SystemExit P0 learning, which limited
# its fix to formatters). Rule authors who legitimately want to abort the
# run raise an Exception subclass NOT in this tuple — ``RuntimeError`` is
# the canonical choice; see ``LintRuleError`` docstring.
#
# ``KeyError`` is intentionally NOT listed separately — it is a subclass
# of ``LookupError``, which is already in the tuple, so adding it would
# be dead coverage.
_RULE_EXCEPTION_TUPLE: tuple[type[BaseException], ...] = (
    SystemExit,
    ValueError,
    TypeError,
    AttributeError,
    LookupError,
    LintRuleError,
)


class LintEngine:
    """Descriptor-tree walker + per-instance rule registry.

    Construct an engine, load rule packs into it, then call
    :meth:`run` per lint pass. Each engine instance is independent;
    there is no process-global registry. Tests construct fresh
    engines for isolation; callers wanting "fresh state" on an
    existing engine call :meth:`reset`.

    Attributes (introspectable for tests / D3 CLI ``--list-rules``):
        See :meth:`__init__`.
    """

    def __init__(self) -> None:
        """Initialize empty per-instance registry state."""
        self._loaded_specs: dict[str, LintRuleSpec] = {}
        self._loaded_module_names: set[str] = set()
        # Per-run accumulators (reset at every ``run()`` entry; declared
        # here for type-checker visibility).
        self._findings: list[LintFinding] = []
        self._runtime_warnings: list[LintRuntimeWarning] = []
        self._filtered_count: int = 0
        self._current_profile: LintProfile | None = None

    # ------------------------------------------------------------------
    # Pack loading and reset
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Clear engine state (loaded rules + loaded module names).

        Returns the engine to its constructed state. Per-run
        accumulators (findings, runtime warnings, filtered_count) are
        also cleared, though ``run()`` resets them at every entry, so
        this clearing is mostly defensive. Does NOT touch
        ``_lint_spec`` attributes on rule functions — those live on
        the function objects, are module-scoped, and survive engine
        reset by design.
        """
        self._loaded_specs.clear()
        self._loaded_module_names.clear()
        self._findings.clear()
        self._runtime_warnings.clear()
        self._filtered_count = 0
        self._current_profile = None

    def load_rule_pack(self, module: ModuleType) -> None:
        """Load every entry from ``module.RULES`` per-instance.

        Echoes compat's ``SchemaChecker.load_rule_pack(module)``
        signature exactly (``schema/checker.py:217``). Caller imports
        the module first; the engine reads ``module.__name__`` for
        idempotency tracking and ``module.RULES`` for the rule-list.

        Stage-then-commit: builds a staging mapping of
        ``rule_id → LintRuleSpec`` from ``module.RULES``, validates
        intra-pack duplicates AND cross-pack duplicates against
        already-loaded rules, then commits or rolls back. On
        ``DuplicateRuleError``, the engine state is unchanged from
        before the call.

        Idempotent for the same module name: calling
        ``load_rule_pack`` a second time with the same module
        short-circuits (returns immediately, engine state unchanged).

        Args:
            module: An imported module exposing a module-level
                ``RULES`` attribute — a tuple of ``@lint_rule``-
                decorated callables.

        Raises:
            AttributeError: If ``module`` has no ``RULES`` attribute.
            TypeError: If any entry in ``module.RULES`` lacks a
                ``_lint_spec`` attribute (i.e., wasn't decorated with
                ``@lint_rule``).
            DuplicateRuleError: If two rule functions in the pack
                share a ``rule_id`` (intra-pack duplicate, caught at
                staging time), OR if any rule_id in the pack is
                already loaded by a previously-loaded pack (cross-
                pack duplicate, caught before commit). The engine
                state is rolled back on either failure.
        """
        if module.__name__ in self._loaded_module_names:
            return  # idempotent
        rules = getattr(module, "RULES", None)
        if rules is None:
            raise AttributeError(
                f"rule pack {module.__name__!r} has no RULES attribute. "
                f"Rule packs must expose a module-level "
                f"`RULES = (decorated_fn_1, decorated_fn_2, ...)` tuple."
            )

        # Stage: build per-rule_id mapping; intra-pack collisions raise.
        staging: dict[str, LintRuleSpec] = {}
        for fn in rules:
            spec = getattr(fn, "_lint_spec", None)
            if spec is None:
                raise TypeError(
                    f"{fn!r} in {module.__name__}.RULES is not "
                    f"@lint_rule-decorated; missing _lint_spec attribute."
                )
            spec_typed = cast(LintRuleSpec, spec)
            if spec_typed.rule_id in staging:
                # Intra-pack duplicate — same rule_id appearing twice in
                # this module's RULES tuple. Raise before mutating engine.
                first_fn = staging[spec_typed.rule_id].fn
                raise DuplicateRuleError(
                    spec_typed.rule_id,
                    cast(Callable[..., Any], first_fn),
                    cast(Callable[..., Any], fn),
                )
            staging[spec_typed.rule_id] = spec_typed

        # Validate: any cross-pack rule_id collision against existing.
        for rid, new_spec in staging.items():
            if rid in self._loaded_specs:
                existing_fn = self._loaded_specs[rid].fn
                raise DuplicateRuleError(
                    rid,
                    cast(Callable[..., Any], existing_fn),
                    cast(Callable[..., Any], new_spec.fn),
                )

        # Commit: only after all validation passes.
        self._loaded_specs.update(staging)
        self._loaded_module_names.add(module.__name__)

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def run(
        self,
        compile_result: CompileResult,
        *,
        profile: LintProfile,
    ) -> LintReport:
        """Walk ``compile_result.root_files`` and produce a ``LintReport``.

        Orchestration (per the plan's High-Level Technical Design):

        1. Snapshot ``compile_result.diagnostics`` at entry (defends
           against mid-walk mutation of the source tuple via
           ``object.__setattr__``).
        2. Compute the unloaded-rule diff (``profile.rule_ids`` minus
           the engine's loaded rule_ids) and emit one
           ``LintRuntimeWarning(category="unloaded_rule")`` per missing
           id.
        3. Filter loaded specs by ``profile.rule_ids`` and bucket by
           ``ElementKind``.
        4. Walk ``root_files`` sorted by basename for cross-platform
           test stability. Within each file, dispatch FILE → SERVICE
           (and per-service METHOD) → ENUM (and per-enum ENUM_VALUE)
           → MESSAGE (depth-first into nested enums and messages).
           At every walk level, descriptors are sorted lex by
           ``full_name`` with file-`.name` tie-break for ambiguous
           packages.
        5. Per-rule dispatch wraps the callable in a narrow exception
           tuple including ``SystemExit`` (D2-specific divergence
           from R16; see Key Technical Decisions in the plan).
        6. The emit callback filters by ``profile.min_severity`` at
           emit time; filtered findings increment ``filtered_count``
           and never reach ``LintReport.findings``.
        7. Returns a ``LintReport`` with all accumulators.

        Args:
            compile_result: The output of
                ``compile_protos_to_result``. The engine reads
                ``root_files`` (the files to lint) and ``pool`` (for
                cross-file lookups by rules); ``diagnostics`` is
                passed through verbatim.
            profile: The active ``LintProfile``. Selects rules by
                ``rule_ids``, filters severity by ``min_severity``,
                applies per-rule overrides via
                ``rule_severity_overrides``.

        Returns:
            A populated ``LintReport``. Findings preserve
            walk-emission order (file basename → per-level full_name
            sort → rule registration order within each ElementKind).
        """
        # Step 1: snapshot compile diagnostics.
        compile_diagnostics = tuple(compile_result.diagnostics)

        # Reset per-run accumulators.
        self._findings = []
        self._runtime_warnings = []
        self._filtered_count = 0
        self._current_profile = profile

        # Step 2: unloaded-rule diff (one warning per missing rule_id).
        loaded_ids = set(self._loaded_specs.keys())
        for rid in sorted(profile.rule_ids - loaded_ids):
            self._runtime_warnings.append(
                LintRuntimeWarning(
                    category="unloaded_rule",
                    rule_id=rid,
                    message=(
                        f"rule {rid!r} is named in profile {profile.name!r} "
                        f"but not loaded into the engine"
                    ),
                ),
            )

        # Step 3: filter loaded specs by profile.rule_ids; bucket by element.
        active_specs = [
            spec
            for rid, spec in self._loaded_specs.items()
            if rid in profile.rule_ids
        ]
        group_by_kind: dict[ElementKind, list[LintRuleSpec]] = {
            kind: [] for kind in ElementKind
        }
        for spec in active_specs:
            group_by_kind[spec.element].append(spec)

        # Step 4: walk root_files (sorted by basename for cross-platform
        # stability; tie-break by full path for absolute determinism).
        for fname in sorted(
            compile_result.root_files,
            key=lambda f: (os.path.basename(f), f),
        ):
            try:
                fd = compile_result.pool.FindFileByName(fname)
            except KeyError:
                # Defensive: root_files name not in pool (compile failure
                # path). Skip; no descriptor → no walk for this file.
                continue
            self._dispatch_file(fd, group_by_kind, profile)

        # Step 7: build report.
        return LintReport(
            findings=tuple(self._findings),
            diagnostics=compile_diagnostics,
            profiles_run=(profile.name,),
            rules_run=tuple(spec.rule_id for spec in active_specs),
            runtime_warnings=tuple(self._runtime_warnings),
            filtered_count=self._filtered_count,
        )

    # ------------------------------------------------------------------
    # Dispatch helpers — one per ElementKind
    # ------------------------------------------------------------------

    def _dispatch_file(
        self,
        fd: proto_descriptor.FileDescriptor,
        group_by_kind: dict[ElementKind, list[LintRuleSpec]],
        profile: LintProfile,
    ) -> None:
        """Walk a single file: dispatch FILE rules, then descend."""
        for spec in group_by_kind[ElementKind.FILE]:
            ctx = self._build_file_ctx(fd, spec, profile)
            self._invoke_rule(spec, ctx)

        for service in self._sorted_by_full_name(fd.services_by_name.values()):
            for spec in group_by_kind[ElementKind.SERVICE]:
                ctx_svc = self._build_service_ctx(service, fd, spec, profile)
                self._invoke_rule(spec, ctx_svc)
            for method in self._sorted_by_name(service.methods):
                for spec in group_by_kind[ElementKind.METHOD]:
                    ctx_m = self._build_method_ctx(
                        method, service, fd, spec, profile,
                    )
                    self._invoke_rule(spec, ctx_m)

        for enum in self._sorted_by_full_name(fd.enum_types_by_name.values()):
            self._dispatch_enum(enum, fd, group_by_kind, profile)

        for message in self._sorted_by_full_name(fd.message_types_by_name.values()):
            self._dispatch_message(message, fd, group_by_kind, profile)

    def _dispatch_enum(
        self,
        enum: proto_descriptor.EnumDescriptor,
        fd: proto_descriptor.FileDescriptor,
        group_by_kind: dict[ElementKind, list[LintRuleSpec]],
        profile: LintProfile,
    ) -> None:
        """Walk an enum: dispatch ENUM rules, then ENUM_VALUE rules."""
        for spec in group_by_kind[ElementKind.ENUM]:
            ctx = self._build_enum_ctx(enum, fd, spec, profile)
            self._invoke_rule(spec, ctx)
        # enum.values is the proto-declared order, which matches the user's
        # source. Sorting by name would re-order values like UNSPECIFIED=0
        # ahead of FOO=1 unstably; preserve declared order for ENUM_VALUE.
        for value in enum.values:
            for spec in group_by_kind[ElementKind.ENUM_VALUE]:
                ctx_val = self._build_enum_value_ctx(
                    value, enum, fd, spec, profile,
                )
                self._invoke_rule(spec, ctx_val)

    def _dispatch_message(
        self,
        message: proto_descriptor.Descriptor,
        fd: proto_descriptor.FileDescriptor,
        group_by_kind: dict[ElementKind, list[LintRuleSpec]],
        profile: LintProfile,
    ) -> None:
        """Walk a message: MESSAGE → FIELD → ONEOF → nested ENUM/MESSAGE."""
        for spec in group_by_kind[ElementKind.MESSAGE]:
            ctx = self._build_message_ctx(message, fd, spec, profile)
            self._invoke_rule(spec, ctx)

        for field in self._sorted_by_name(message.fields):
            for spec in group_by_kind[ElementKind.FIELD]:
                ctx_f = self._build_field_ctx(field, message, fd, spec, profile)
                self._invoke_rule(spec, ctx_f)

        for oneof in self._sorted_by_name(message.oneofs):
            for spec in group_by_kind[ElementKind.ONEOF]:
                ctx_o = self._build_oneof_ctx(oneof, message, fd, spec, profile)
                self._invoke_rule(spec, ctx_o)

        for nested_enum in self._sorted_by_full_name(message.enum_types):
            self._dispatch_enum(nested_enum, fd, group_by_kind, profile)

        for nested_message in self._sorted_by_full_name(message.nested_types):
            self._dispatch_message(nested_message, fd, group_by_kind, profile)

    # ------------------------------------------------------------------
    # Per-rule invocation + emit
    # ------------------------------------------------------------------

    def _invoke_rule(self, spec: LintRuleSpec, ctx: Any) -> None:
        """Call the rule's fn(ctx); record a runtime warning on caught exc.

        ``descriptor_path`` for caught exceptions is read from
        ``ctx.location()`` rather than a separately-passed location
        argument — every context dataclass already produces the
        canonical ``LintLocation`` for its element kind, and the dual
        construction was a divergence-risk surface (the dispatch site
        and the context could in principle disagree on the location).
        """
        if spec.fn is None:
            return  # placeholder spec — defensive; production paths reject None
        try:
            spec.fn(ctx)
        except _RULE_EXCEPTION_TUPLE as exc:
            self._runtime_warnings.append(
                LintRuntimeWarning(
                    category="rule_exception",
                    rule_id=spec.rule_id,
                    message=str(exc) if str(exc) else repr(exc),
                    exception_type=exc.__class__.__name__,
                    descriptor_path=str(ctx.location()),
                ),
            )

    def _emit(self, finding: LintFinding) -> None:
        """Append finding, filtering by ``profile.min_severity``.

        ``finding.severity`` is already the effective severity — set
        inside ``_LintContextEmitMixin.emit()`` via the engine-injected
        ``_effective_severity`` closure (see ``model.py:643-646``). This
        callback's job is the min-severity gate only.
        """
        # _current_profile is set at run() entry; this callback is only
        # invoked through engine-built contexts during a run.
        assert self._current_profile is not None  # mypy + invariant
        min_rank = _SEVERITY_RANK[self._current_profile.min_severity]
        finding_rank = _SEVERITY_RANK[finding.severity]
        if finding_rank < min_rank:
            self._filtered_count += 1
            return
        self._findings.append(finding)

    # ------------------------------------------------------------------
    # Severity resolution
    # ------------------------------------------------------------------

    def _make_effective_severity(
        self,
        spec: LintRuleSpec,
        profile: LintProfile,
    ) -> Callable[[str], LintSeverity]:
        """Return a closure resolving severity for one (spec, profile) pair.

        Order: spec.severity_for(violation_kind), then apply
        profile.rule_severity_overrides[rule_id] if set (overrides
        every violation_kind of the rule under this profile).
        """
        override = profile.rule_severity_overrides.get(spec.rule_id)

        def resolve(violation_kind: str) -> LintSeverity:
            if override is not None:
                return override
            return spec.severity_for(violation_kind)

        return resolve

    # ------------------------------------------------------------------
    # Context builders — one per ElementKind, all wire _emit_fn / _rule_id
    # / _effective_severity for the (spec, profile) pair.
    # ------------------------------------------------------------------

    def _build_file_ctx(
        self,
        fd: proto_descriptor.FileDescriptor,
        spec: LintRuleSpec,
        profile: LintProfile,
    ) -> FileLintContext:
        return FileLintContext(
            file=fd,
            pool=fd.pool,
            profile=profile.name,
            _emit_fn=self._emit,
            _rule_id=spec.rule_id,
            _effective_severity=self._make_effective_severity(spec, profile),
        )

    def _build_service_ctx(
        self,
        service: proto_descriptor.ServiceDescriptor,
        fd: proto_descriptor.FileDescriptor,
        spec: LintRuleSpec,
        profile: LintProfile,
    ) -> ServiceLintContext:
        return ServiceLintContext(
            service=service,
            file=fd,
            pool=fd.pool,
            profile=profile.name,
            _emit_fn=self._emit,
            _rule_id=spec.rule_id,
            _effective_severity=self._make_effective_severity(spec, profile),
        )

    def _build_method_ctx(
        self,
        method: proto_descriptor.MethodDescriptor,
        service: proto_descriptor.ServiceDescriptor,
        fd: proto_descriptor.FileDescriptor,
        spec: LintRuleSpec,
        profile: LintProfile,
    ) -> MethodLintContext:
        return MethodLintContext(
            method=method,
            service=service,
            file=fd,
            pool=fd.pool,
            profile=profile.name,
            _emit_fn=self._emit,
            _rule_id=spec.rule_id,
            _effective_severity=self._make_effective_severity(spec, profile),
        )

    def _build_enum_ctx(
        self,
        enum: proto_descriptor.EnumDescriptor,
        fd: proto_descriptor.FileDescriptor,
        spec: LintRuleSpec,
        profile: LintProfile,
    ) -> EnumLintContext:
        return EnumLintContext(
            enum=enum,
            file=fd,
            pool=fd.pool,
            profile=profile.name,
            _emit_fn=self._emit,
            _rule_id=spec.rule_id,
            _effective_severity=self._make_effective_severity(spec, profile),
        )

    def _build_enum_value_ctx(
        self,
        value: proto_descriptor.EnumValueDescriptor,
        enum: proto_descriptor.EnumDescriptor,
        fd: proto_descriptor.FileDescriptor,
        spec: LintRuleSpec,
        profile: LintProfile,
    ) -> EnumValueLintContext:
        return EnumValueLintContext(
            value=value,
            enum=enum,
            file=fd,
            pool=fd.pool,
            profile=profile.name,
            _emit_fn=self._emit,
            _rule_id=spec.rule_id,
            _effective_severity=self._make_effective_severity(spec, profile),
        )

    def _build_message_ctx(
        self,
        message: proto_descriptor.Descriptor,
        fd: proto_descriptor.FileDescriptor,
        spec: LintRuleSpec,
        profile: LintProfile,
    ) -> MessageLintContext:
        return MessageLintContext(
            message=message,
            file=fd,
            pool=fd.pool,
            profile=profile.name,
            _emit_fn=self._emit,
            _rule_id=spec.rule_id,
            _effective_severity=self._make_effective_severity(spec, profile),
        )

    def _build_field_ctx(
        self,
        field: proto_descriptor.FieldDescriptor,
        message: proto_descriptor.Descriptor,
        fd: proto_descriptor.FileDescriptor,
        spec: LintRuleSpec,
        profile: LintProfile,
    ) -> FieldLintContext:
        return FieldLintContext(
            field=field,
            message=message,
            file=fd,
            pool=fd.pool,
            profile=profile.name,
            _emit_fn=self._emit,
            _rule_id=spec.rule_id,
            _effective_severity=self._make_effective_severity(spec, profile),
        )

    def _build_oneof_ctx(
        self,
        oneof: proto_descriptor.OneofDescriptor,
        message: proto_descriptor.Descriptor,
        fd: proto_descriptor.FileDescriptor,
        spec: LintRuleSpec,
        profile: LintProfile,
    ) -> OneofLintContext:
        return OneofLintContext(
            oneof=oneof,
            message=message,
            file=fd,
            pool=fd.pool,
            profile=profile.name,
            _emit_fn=self._emit,
            _rule_id=spec.rule_id,
            _effective_severity=self._make_effective_severity(spec, profile),
        )

    # ------------------------------------------------------------------
    # Sort helpers — guarantee deterministic walk order independent of
    # protobuf binding iteration semantics.
    # ------------------------------------------------------------------

    @staticmethod
    def _sorted_by_full_name(items: Iterable[Any]) -> list[Any]:
        """Sort descriptors lex by ``full_name``, tie-break by ``name``.

        File descriptors lack ``full_name`` and fall back to ``name``.
        The ``name`` tie-break catches the ambiguous-package case
        (two files declaring the same ``package empty;`` produce
        descriptors with identical ``full_name``s).
        """
        return sorted(
            items,
            key=lambda x: (getattr(x, "full_name", x.name), x.name),
        )

    @staticmethod
    def _sorted_by_name(items: Iterable[Any]) -> list[Any]:
        """Sort items lex by ``name``. Used for fields / oneofs / methods."""
        return sorted(items, key=lambda x: x.name)
