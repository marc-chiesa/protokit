"""``LintEngine`` — descriptor-tree walker + per-instance rule registry.

Adopts compat's per-instance design at
``schema/checker.py:136-143, 217-235`` — each engine instance owns
its loaded-rule dict; there is no process-global registry. The
``RULES`` attribute name is reused but the **wire format differs**:
compat's ``module.RULES`` is a sequence of ``(rule_id, plugin_fn)``
tuples; lint's ``module.RULES`` is a sequence of bare
``@lint_rule``-decorated callables (the ``rule_id`` lives on
``fn._lint_spec``). A pack written for one engine cannot be loaded
into the other; the divergence is intentional (lint co-locates
rule_id with the rule definition via the decorator) and surfaced
loudly here so D7 plugin authors don't expect cross-engine reuse.

``load_rule_pack(module: ModuleType)`` mirrors compat's signature
exactly. Reads ``module.RULES``, extracts each function's
``_lint_spec``, and registers per-instance with cross-pack
``DuplicateRuleError`` detection (compat does NOT raise on
cross-pack collision — another behaviour divergence; lint chose to
surface duplicates loudly). ``run(compile_result, *, profile)``
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

**Pre-walk accumulators (cross-file rule infrastructure).** Before
Step 4's per-file walk, ``run()`` invokes two sibling pre-walk
accumulators that capture per-file state for cross-file rule
consumers. They differ DELIBERATELY in iteration scope:

- ``_build_package_options_accumulator`` (D6b U4a / R7
  PACKAGE_SAME_* family) — iterates ``pool_file_names`` (full pool
  including transitive imports) and captures FileOptions values
  per-(package, option_attr, filename). R7's per-option
  cross-language-namespace conflicts intentionally span the
  import boundary.
- ``_build_directory_package_accumulator`` (D6c U1 / R8 + R8b
  package/same-directory + package/directory-same-package) —
  iterates ``root_files`` (per-invocation scope only) and captures
  per-(package, filename, dirname). R8/R8b's per-directory
  file-organization rule is intentionally local to the user-owned
  files (buf v1.69.0 does not cross-fire across module boundaries
  per the D6c KTD-4 (d) empirical correction).

Both accumulators snapshot into instance attributes
(``_current_*``) at Step 3.5 / 3.5b and clear in the ``finally``
block of ``run()``. The accumulator-consumer rules access the
snapshot via ``ctx.package_options`` / ``ctx.directory_packages``
on their ``FileLintContext``. The divergence in iteration scope
is load-bearing — DO NOT unify the accumulators without empirical
re-verification against buf parity for both rule families.
"""

from __future__ import annotations

import os
import posixpath
from collections.abc import Callable, Iterable, Mapping
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, cast

from google.protobuf.message import DecodeError

from protokit._cli_utils import _scrub_exc_message
from protokit.schema.lint._cli_utils import _safe_for_stderr
from protokit.schema.lint.model import (
    SEVERITY_RANK,
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
    from google.protobuf.descriptor_pb2 import FileDescriptorProto

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
#
# ``DecodeError`` (D6d U2 ce:review REL-1 + SEC-002) is added because
# option-aware rules using the dynamic-pool re-parse pattern
# (``parsed.MergeFromString(descriptor.GetOptions().SerializeToString())``)
# can encounter malformed serialized options bytes if a future protobuf
# version, protoxy upgrade, or descriptor-set corruption surfaces them.
# Without ``DecodeError`` in the tuple, the exception propagates uncaught
# past ``_invoke_rule`` and crashes ``engine.run()`` instead of being
# recorded as a ``rule_exception`` warning. ``DecodeError`` is the only
# subclass of ``google.protobuf.message.Error`` the engine needs to
# anticipate; the parent class is not added because no other
# ``Error`` subclass is reachable via the current rule-callable surface.
_RULE_EXCEPTION_TUPLE: tuple[type[BaseException], ...] = (
    SystemExit,
    ValueError,
    TypeError,
    AttributeError,
    LookupError,
    DecodeError,
    LintRuleError,
)


class LintEngine:
    """Descriptor-tree walker + per-instance rule registry.

    Construct an engine, load rule packs into it, then call
    :meth:`run` per lint pass. Each engine instance is independent;
    there is no process-global registry. Tests construct fresh
    engines for isolation; callers wanting "fresh state" on an
    existing engine call :meth:`reset`.

    **Not thread-safe; not reentrant.** Per-run accumulators
    (``_findings``, ``_runtime_warnings``, ``_filtered_count``,
    ``_current_profile``, ``_current_source_info_descriptors``,
    ``_current_package_options``, ``_current_directory_packages``)
    are instance attributes mutated during :meth:`run`. Concurrent or
    nested ``run()`` calls on the same engine corrupt the accumulators
    silently. :meth:`run` raises ``RuntimeError`` on detected reentrancy
    (a rule recursing into ``engine.run()`` mid-walk). The
    ``_current_*`` snapshot fields are ``None`` at construction time
    and cleaned by the ``finally`` block of every :meth:`run`
    invocation — ``reset()`` does not touch them since every entry to
    ``run()`` re-snapshots them (only ``_current_profile`` doubles as
    the reentrancy guard and is cleared by ``reset()``). Concurrent
    threads must use one engine instance per thread. Engines themselves
    are cheap to construct, so per-thread instances are the recommended
    pattern.

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
        # Per-run snapshot of the active ``CompileResult.source_info_descriptors``
        # (D6b U2 / R6b). Read by the 5 R6 ElementKind context builders
        # so comment-aware rules in U3 can call ``leading_comment`` on the
        # ctx-provided mapping without parameter-threading through every
        # dispatch helper. Set immediately after the reentrancy guard in
        # :meth:`run` and cleared in the ``finally`` block. The set-after-
        # guard ordering is load-bearing: it lets the existing
        # ``_current_profile`` guard catch reentrant ``run()`` calls
        # before this field can be corrupted.
        self._current_source_info_descriptors: (
            Mapping[str, FileDescriptorProto] | None
        ) = None
        # Per-run snapshot of the Step 3.5 pre-walk's package_options
        # accumulator (D6b U4a / R7). Shape:
        # Mapping[package, Mapping[option_attr, Mapping[fname, str | None]]]
        # with 3-level MappingProxyType wraps. None when the pre-walk
        # early-returned (pool_file_names was empty). Set in ``run()``
        # after Step 3 + cleared in the ``finally`` block.
        self._current_package_options: (
            Mapping[str, Mapping[str, Mapping[str, str | None]]] | None
        ) = None
        # Per-run snapshots of the Step 3.5b cross-file directory
        # pre-walk's accumulators (D6c U1 / R8 + R8b). Two views of the
        # same {package, filename, dirname} triples produced in one pass
        # so each rule callable gets O(1) access to its primary key:
        #
        # _current_directory_packages: Mapping[pkg, Mapping[fname, dirname]]
        #   — primary view for R8 (package/same-directory). Lookup by
        #   package name → set of (fname, dirname); fires when the set
        #   of distinct dirnames > 1.
        # _current_directory_packages_by_dir:
        #   Mapping[dirname, Mapping[pkg, frozenset[fname]]] — inverted
        #   view for R8b (package/directory-same-package). Lookup by
        #   directory → set of (pkg, fnames-in-that-dir); fires when
        #   the set of distinct packages > 1 (or when a packageless
        #   entry mixes with a declared-package entry, per KTD-4 (b)).
        #
        # Both wraps are 2-level MappingProxyType. Both ``None`` when the
        # pre-walk early-returned (root_files was empty). Set together
        # in ``run()`` after Step 3 + cleared together in the ``finally``
        # block. The dual-view design prevents R8b's per-file O(N) scan
        # over the per-package view that would otherwise produce O(N²)
        # behavior on large projects.
        #
        # Diverges from R7's accumulator in iteration scope: R8/R8b's
        # per-module-isolation semantic (buf does not cross-fire across
        # module boundaries) scopes to ``root_files``, NOT
        # ``pool_file_names``.
        self._current_directory_packages: (
            Mapping[str, Mapping[str, str]] | None
        ) = None
        self._current_directory_packages_by_dir: (
            Mapping[str, Mapping[str, frozenset[str]]] | None
        ) = None

    # ------------------------------------------------------------------
    # Public accessors
    # ------------------------------------------------------------------

    @property
    def has_rules(self) -> bool:
        """True iff at least one rule has been loaded.

        Public accessor for the R9 zero-rules CLI guard. Replaces the
        prior ``_loaded_specs`` dict-truthiness check used by callers.
        """
        return bool(self._loaded_specs)

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

        Mirrors compat's ``SchemaChecker.load_rule_pack(module)``
        signature exactly (``schema/checker.py:217``); two **behaviour
        divergences** worth noting:

        - The expected element type of ``module.RULES`` differs:
          compat expects ``(rule_id, plugin_fn)`` tuples; lint expects
          bare ``@lint_rule``-decorated callables (the rule_id lives
          on ``fn._lint_spec``). A pack cannot be loaded into both
          engines.
        - This method raises ``DuplicateRuleError`` on cross-pack
          ``rule_id`` collisions; compat silently allows duplicates
          (both rules run, producing ambiguous findings under one
          rule_id). Lint chose to fail loudly.
        - This method is idempotent for the same module name (second
          call short-circuits); compat is not (second call double-
          registers).

        Caller imports the module first; the engine reads
        ``module.__name__`` for idempotency tracking and
        ``module.RULES`` for the rule-list.

        Stage-then-commit: builds a staging mapping of
        ``rule_id → LintRuleSpec`` from ``module.RULES``, validates
        intra-pack duplicates AND cross-pack duplicates against
        already-loaded rules, then commits or rolls back. On
        ``DuplicateRuleError``, the engine state is unchanged from
        before the call.

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
        # Reentrancy guard — see class docstring. ``_current_profile`` is
        # set non-None for the duration of ``run()``; a non-None value at
        # entry means a rule is recursing into engine.run(), which would
        # silently corrupt the outer run's accumulators.
        if self._current_profile is not None:
            raise RuntimeError(
                "LintEngine.run() is not reentrant; a rule callable cannot "
                "recurse into engine.run() mid-walk. Construct a separate "
                "LintEngine instance for nested lint passes."
            )

        # Step 1: snapshot compile diagnostics.
        compile_diagnostics = tuple(compile_result.diagnostics)

        # Reset per-run accumulators.
        self._findings = []
        self._runtime_warnings = []
        self._filtered_count = 0
        self._current_profile = profile
        # Snapshot the source-info mapping for the 5 R6 ElementKind
        # context builders (D6b U2 / R6b). Set AFTER the reentrancy
        # guard above so the guard fires first if a rule recurses into
        # ``run()`` mid-walk — preserving the K-1 set-after-guard
        # invariant called out in the U2 plan.
        self._current_source_info_descriptors = (
            compile_result.source_info_descriptors
        )

        try:
            # Step 2: unloaded-rule diff (one warning per missing rule_id).
            # Per KTD-9, ``rid`` (from ``profile.rule_ids``) and
            # ``profile.name`` are operator-supplied strings — pyproject
            # ``profile = ...`` values or ``--profile NAME`` CLI args —
            # so they pass through ``_safe_for_stderr`` at construction
            # time, matching the ``rule_exception`` path below. Without
            # this, an ANSI-escape-bearing profile name would survive
            # into JUnit ``<system-out>`` (where ``xml_safe_text`` does
            # not strip ESC) and SARIF ``message.text`` (where
            # ``json.dumps`` does not escape ESC). The stderr boundary
            # (``_emit_human_runtime_warnings``) is the backstop; this
            # is the primary defense per the dual-sanitization model.
            loaded_ids = set(self._loaded_specs.keys())
            safe_profile_name = _safe_for_stderr(profile.name)
            for rid in sorted(profile.rule_ids - loaded_ids):
                safe_rid = _safe_for_stderr(rid)
                self._runtime_warnings.append(
                    LintRuntimeWarning(
                        category="unloaded_rule",
                        # rule_id flows verbatim into lint_json and lint_sarif
                        # wire formats — json.dumps does NOT escape U+2028/U+2029,
                        # so an attacker-influenced rule_id with embedded line
                        # terminators would survive into machine output and
                        # trigger log-aggregator record injection. Apply the
                        # same sanitizer here as the message slot per the
                        # dual-sanitization model (KTD-9).
                        rule_id=safe_rid,
                        message=(
                            f"rule {safe_rid!r} is named in profile "
                            f"{safe_profile_name!r} but not loaded "
                            f"into the engine"
                        ),
                    ),
                )

            # Step 3: filter loaded specs by profile.rule_ids; bucket by kind.
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

            # Step 3.5: pre-walk file-options accumulator for R7 cross-file
            # PACKAGE_SAME_* rules. Iterates the FULL pool —
            # including transitively-imported protos — so the canonical
            # value computation matches buf's full-module walk; findings
            # still emit only on root_files via Step 4's dispatch gate.
            # Built unconditionally when pool_file_names is non-empty (no
            # lazy-gating; revisit only if SC E7 benchmark exceeds 50ms).
            # No WKT filter (empirically dropped per
            # tests/schema/lint/rules/fixtures/package_same/_buf_smoke/
            # recorded/wkt-conflict.json — buf fires on disagreeing
            # google.protobuf files, so protokit must too).
            # Defensive try/except KeyError mirrors Step 4 below (root_files
            # name not in pool → compile-failure path skip).
            self._current_package_options = self._build_package_options_accumulator(
                compile_result,
            )
            # Step 3.5b (D6c U1 / R8 + R8b): cross-file directory pre-walk.
            # Scoped to ``root_files`` (NOT ``pool_file_names``) per the
            # KTD-4 (d) empirical correction — buf v1.69.0 does not
            # cross-fire PACKAGE_SAME_DIRECTORY / DIRECTORY_SAME_PACKAGE
            # across module boundaries (Phase 0 verification recipes
            # documented in docs/plans/2026-05-18-003-feat-d6c-r8-r8b-
            # cross-file-package-rules-plan.md § Phase 0). Diverges from
            # R7's pool-scope iteration; both are correct for their rule
            # families. DO NOT unify without empirical re-verification.
            (
                self._current_directory_packages,
                self._current_directory_packages_by_dir,
            ) = self._build_directory_package_accumulator(compile_result)

            # Step 4: walk root_files (sorted by basename for cross-platform
            # stability; tie-break by full path for absolute determinism).
            for fname in sorted(
                compile_result.root_files,
                key=lambda f: (os.path.basename(f), f),
            ):
                try:
                    fd = compile_result.pool.FindFileByName(fname)
                except KeyError:
                    # Defensive: root_files name not in pool (compile-failure
                    # path). Skip; no descriptor → no walk for this file.
                    continue
                self._dispatch_file(fd, group_by_kind, profile)

            # Step 7: build report. Pass loaded specs into the
            # report so formatters can render messages from
            # LintRuleSpec.message_template without reaching back into
            # engine internals (critical for D3's human formatter and
            # D4's machine formatters). LintReport.__post_init__
            # snapshots the dict, so we don't need a defensive
            # dict(...) here — same convention findings/runtime_warnings
            # use (engine passes raw sequence; post-init re-tuples).
            return LintReport(
                findings=tuple(self._findings),
                diagnostics=compile_diagnostics,
                profiles_run=(profile.name,),
                rules_run=tuple(spec.rule_id for spec in active_specs),
                runtime_warnings=tuple(self._runtime_warnings),
                filtered_count=self._filtered_count,
                specs=self._loaded_specs,
            )
        finally:
            # Clear _current_profile so the reentrancy guard works for the
            # NEXT run() call AND so escaped-ctx.emit() calls hit the
            # _emit-time guard rather than appending to a stale _findings.
            self._current_profile = None
            # Clear the per-run source-info snapshot too so a subsequent
            # run() with a different compile_result cannot leak the
            # previous run's mapping into rule callbacks.
            self._current_source_info_descriptors = None
            # Clear the per-run package_options accumulator for the same
            # reason — prevent leak across run() invocations.
            self._current_package_options = None
            # Clear the per-run directory_packages accumulators (D6c U1)
            # for the same reason — prevent stale cross-file state from
            # bleeding into a subsequent run() invocation. Both views
            # (per-package + per-directory-inverted) reset together.
            self._current_directory_packages = None
            self._current_directory_packages_by_dir = None

    # ------------------------------------------------------------------
    # Pre-walk accumulator (R7 PACKAGE_SAME_* infrastructure)
    # ------------------------------------------------------------------

    # WKT path prefix is NOT filtered (empirical: buf v1.69.0 fires on
    # disagreeing google.protobuf files per the wkt-conflict smoke
    # fixture). Real WKTs have consistent options across the
    # protobuf-runtime corpus so they never trigger findings in practice;
    # synthetic disagreement cases (vendored stubs, accidental
    # `package google.protobuf` declarations) correctly fire to match buf.

    def _build_package_options_accumulator(
        self, compile_result: CompileResult,
    ) -> Mapping[str, Mapping[str, Mapping[str, str | None]]] | None:
        """Construct the 3-level ``package_options`` accumulator for R7.

        Iterates ``compile_result.pool_file_names`` (the FULL pool
        including transitive imports — superset of ``root_files``) and
        captures each file's ``FileOptions`` values for the 7
        PACKAGE_SAME_* attrs. Bool ``java_multiple_files`` is captured
        as a lowercase string ("true" / "false") to byte-match buf's
        emit format per the empirical mixed-value-java-multiple-files
        smoke fixture.

        Returns ``None`` when ``pool_file_names`` is empty — early-return
        signals to ``_build_file_ctx`` that no accumulator was built
        (test-helper paths + compile-failure paths). Otherwise returns a
        3-level ``MappingProxyType``-wrapped Mapping; mutation at any
        nesting depth raises ``TypeError``.

        Iteration uses ``posixpath.basename`` (NOT ``os.path.basename``)
        so the sort key is platform-independent — protobuf-canonical
        paths use forward slashes regardless of host OS. See
        ``docs/solutions/best-practices/pureposixpath-for-proto-descriptor-file-stem-2026-05-12.md``
        for the canonical rationale (descriptor-walking code outside
        rule callables must use posixpath, not os.path).

        Defensive ``try/except KeyError: continue`` mirrors Step 4's
        existing pattern at the per-fd lookup; matches the existing
        partial-pool-state tolerance and avoids regressing
        compile-failure paths that today produce partial lint reports.

        Lazy import of ``_PACKAGE_SAME_OPTION_ATTR_NAMES`` from
        ``protokit.schema.lint.rules.package_same`` is deferred to
        runtime (not module-top) to preserve the cold-import contract
        for ``protokit.schema`` per
        ``tests/schema/lint/test_cold_import_extended.py``. Since
        D6b U7 registered ``package_same`` in BUILTIN_PACKS, the
        package_same module loads at engine-init time anyway, so this
        deferred import is a no-op at runtime — kept here as a defense
        against any future BUILTIN_PACKS rearrangement that might
        defer the load.
        """
        if not compile_result.pool_file_names:
            return None

        # Lazy import — see method docstring for cold-import contract.
        from protokit.schema.lint.rules.package_same import (  # noqa: PLC0415
            _PACKAGE_SAME_OPTION_ATTR_NAMES,
        )

        package_options: dict[str, dict[str, dict[str, str | None]]] = {}
        for fname in sorted(
            compile_result.pool_file_names,
            key=lambda f: (posixpath.basename(f), f),
        ):
            # ce:review follow-up: widened from KeyError-only to also catch
            # AttributeError + ValueError. opts.HasField() raises ValueError
            # for non-presence-tracked fields (proto3 repeated/map/implicit
            # scalars); a future _PACKAGE_SAME_OPTION_ATTRS extension to
            # such a field would otherwise propagate uncaught out of run()
            # and violate the engine's failure-containment posture. All
            # current 7 attrs are presence-tracked FileOptions scalars —
            # defensive, not currently-firing.
            try:
                fd = compile_result.pool.FindFileByName(fname)
                pkg = fd.package
                opts = fd.GetOptions()
                per_pkg = package_options.setdefault(pkg, {})
                for attr in _PACKAGE_SAME_OPTION_ATTR_NAMES:
                    per_attr = per_pkg.setdefault(attr, {})
                    if opts.HasField(attr):
                        raw = getattr(opts, attr)
                        # Empirical: buf renders booleans as lowercase
                        # ("false"/"true"), not Python's title-case ("False"/"True").
                        # Per recorded/mixed-value-java-multiple-files.json.
                        if isinstance(raw, bool):
                            per_attr[fname] = str(raw).lower()
                        else:
                            per_attr[fname] = str(raw)
                    else:
                        per_attr[fname] = None
            except (KeyError, AttributeError, ValueError):
                continue

        # 3-level MappingProxyType wrap (defense-in-depth against
        # accidental mutation by co-authored rule code; NOT a security
        # boundary, since user-pack code via --rule-pack runs in-process
        # with full Python introspection).
        wrapped: dict[str, Mapping[str, Mapping[str, str | None]]] = {}
        for pkg, per_pkg_dict in package_options.items():
            wrapped_per_pkg: dict[str, Mapping[str, str | None]] = {}
            for attr, per_attr_dict in per_pkg_dict.items():
                wrapped_per_pkg[attr] = MappingProxyType(per_attr_dict)
            wrapped[pkg] = MappingProxyType(wrapped_per_pkg)
        return MappingProxyType(wrapped)

    # ------------------------------------------------------------------
    # Pre-walk accumulator (R8 + R8b cross-file directory infrastructure)
    # ------------------------------------------------------------------

    def _build_directory_package_accumulator(
        self, compile_result: CompileResult,
    ) -> tuple[
        Mapping[str, Mapping[str, str]] | None,
        Mapping[str, Mapping[str, frozenset[str]]] | None,
    ]:
        """Construct dual-view ``directory_packages`` accumulators for R8/R8b.

        Iterates ``compile_result.root_files`` (NOT ``pool_file_names``;
        this DIVERGES from R7's pre-walk per the KTD-4 (d) empirical
        correction) and captures each file's ``(fd.package, fname,
        dirname)`` triple. Returns a tuple ``(by_package, by_directory)``
        — two views of the same data, both 2-level
        ``MappingProxyType``-wrapped:

        - ``by_package: Mapping[pkg, Mapping[fname, dirname]]`` — R8's
          primary view. Lookup by package name to find the set of
          distinct directories containing that package.
        - ``by_directory: Mapping[dirname, Mapping[pkg, frozenset[fname]]]``
          — R8b's primary view (inverted index). Lookup by directory
          to find the set of distinct packages declared by files in
          that directory.

        Both views are built in one pass over ``root_files`` so the
        iteration cost is paid once. The inverted view is essential
        for R8b's per-file callable to achieve O(1) directory lookup
        instead of O(N) scan over the per-package view (which would
        produce O(N²) total across N root files, per the D6c U1
        ce:review ADV-1 finding).

        Both views return ``None`` when ``root_files`` is empty —
        early-return signals to rule callables that no accumulator
        was built (test-helper paths + compile-failure paths).

        **Iteration scope rationale** (the divergence from R7): buf
        v1.69.0 does NOT cross-fire ``PACKAGE_SAME_DIRECTORY`` /
        ``DIRECTORY_SAME_PACKAGE`` across module boundaries
        (empirically verified — two-module buf.yaml with same-package
        conflicts exits 0; reconstruction recipes documented in the
        D6c plan's Phase 0 section). protokit's analog to buf's
        "module" is the set of files protokit was invoked on =
        ``root_files``. R7's per-option cross-language-namespace
        conflicts INTENTIONALLY span the import boundary (a vendored
        ``java_package`` conflict matters to downstream consumers
        regardless of where the file lives); R8 / R8b's per-directory
        file-organization rule is INTENTIONALLY local to the
        user-owned files. **"Correcting" this back to
        ``pool_file_names`` would cause R8/R8b to fire on
        transitively-imported files outside the user's control —
        spurious findings on every ``vendor/``-style import.**

        **Empty-package files are INCLUDED** (NOT skipped) per
        KTD-4 (b). buf v1.69.0 fires R8b on packageless files mixed
        with declared-package files in the same directory, using a
        distinct message template
        (``"Package \"X\" and file with no package detected within
        directory \"Y\"."``). The accumulator therefore tracks
        packageless files under an empty-string key; the R8b rule
        callable (U2) discriminates the mixed case.

        **Proto-root canonicalization** per KTD-4 (c): files at the
        proto-root render their parent as ``"."``. Empirically
        verified — buf renders ``"directory \".\""``. Implementation:
        ``posixpath.dirname(fname) or "."``.

        **No WKT filter** at ``google/protobuf/`` — mirror R7's posture
        per KTD-4 (a). Single-file Phase 0 fixture was inconclusive;
        U3 parity gate establishes empirical lock against a multi-dir
        ``google.protobuf`` fixture.

        Defensive ``try/except KeyError: continue`` for the
        ``FindFileByName`` lookup — partial-pool-state tolerance for
        compile-failure paths. Narrower than R7's exception tuple
        because the body only calls ``FindFileByName`` (raises
        ``KeyError`` on missing pool entry), reads ``fd.package`` (plain
        attribute), and calls ``posixpath.dirname`` (pure Python on
        ``str``). R7's tuple was widened to ``(KeyError, AttributeError,
        ValueError)`` because ``opts.HasField()`` raises ``ValueError``
        for non-presence-tracked fields and ``getattr(opts, attr)``
        raises ``AttributeError`` for unknown attrs; neither call
        appears in this body.

        Iteration uses ``posixpath.basename`` (NOT ``os.path.basename``)
        for cross-platform determinism per the canonical convention.

        Returns ``None`` when ``root_files`` is empty so test-helper
        paths + compile-failure paths skip the accumulator build; rule
        callables early-return on ``None``.
        """
        if not compile_result.root_files:
            return (None, None)

        # Single pass over root_files captures both per-package and
        # per-directory views.
        directory_packages: dict[str, dict[str, str]] = {}
        packages_by_dir: dict[str, dict[str, set[str]]] = {}
        for fname in sorted(
            compile_result.root_files,
            key=lambda f: (posixpath.basename(f), f),
        ):
            try:
                fd = compile_result.pool.FindFileByName(fname)
            except KeyError:
                continue
            pkg = fd.package
            dirname = posixpath.dirname(fname) or "."
            directory_packages.setdefault(pkg, {})[fname] = dirname
            packages_by_dir.setdefault(dirname, {}).setdefault(pkg, set()).add(fname)

        # 2-level MappingProxyType wrap of the per-package view
        # (defense-in-depth against accidental mutation).
        by_package: dict[str, Mapping[str, str]] = {}
        for pkg, per_pkg_dict in directory_packages.items():
            by_package[pkg] = MappingProxyType(per_pkg_dict)

        # 2-level MappingProxyType wrap of the per-directory view. The
        # inner fname-set is frozen to frozenset (no MappingProxyType
        # for sets — frozenset is the immutable-by-construction analog).
        by_directory: dict[str, Mapping[str, frozenset[str]]] = {}
        for dirname, per_dir_dict in packages_by_dir.items():
            frozen_per_dir: dict[str, frozenset[str]] = {
                pkg: frozenset(fnames) for pkg, fnames in per_dir_dict.items()
            }
            by_directory[dirname] = MappingProxyType(frozen_per_dir)

        return (
            MappingProxyType(by_package),
            MappingProxyType(by_directory),
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
            # Q16 content-safety: the message field must NOT include
            # raw exception tracebacks or filesystem paths. Two
            # layers run on every rule_exception emit:
            #
            # 1. ``_scrub_exc_message`` strips the filename from
            #    ``OSError`` subclasses (defense-in-depth for a
            #    future widening of ``_RULE_EXCEPTION_TUPLE``;
            #    OSError is not in the tuple today).
            # 2. ``_safe_for_stderr`` (KTD-9) collapses all ASCII
            #    control characters to spaces so a multi-line
            #    exception message cannot forge fake
            #    ``warning[lint-runtime]:`` or ``error[lint-CODE]:``
            #    lines in downstream stderr surfaces.
            #
            # ``repr(exc)`` fallback preserves the pre-U4 behavior
            # for exceptions whose ``str()`` is empty. ``exception_type``
            # carries the precise class name for programmatic filtering.
            scrubbed = _scrub_exc_message(exc) or repr(exc)
            safe_message = _safe_for_stderr(scrubbed)
            # ``spec.rule_id`` flows verbatim into lint_json / lint_sarif wire
            # formats. ``json.dumps`` does NOT escape U+2028/U+2029, so an
            # attacker-influenced rule_id with embedded Unicode line terminators
            # survives into machine output and triggers log-aggregator record
            # injection. Sanitize at construction time per KTD-9, mirroring the
            # ``unloaded_rule`` arm above.
            safe_rule_id = _safe_for_stderr(spec.rule_id)
            self._runtime_warnings.append(
                LintRuntimeWarning(
                    category="rule_exception",
                    rule_id=safe_rule_id,
                    message=safe_message,
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
        # ``_current_profile`` is set at ``run()`` entry and cleared in the
        # ``finally`` block. A None value here means a captured ctx escaped
        # the run and called emit() afterward — raise loudly rather than
        # appending to the discarded accumulator. ``assert`` would suffice
        # at full strictness but is stripped under ``python -O``; an
        # explicit raise survives optimisation.
        if self._current_profile is None:
            raise RuntimeError(
                "LintEngine._emit() called outside of an active run() — a "
                "rule callable likely captured its ctx and called "
                "ctx.emit() after run() returned. ctx is only valid for "
                "the duration of the rule's invocation."
            )
        min_rank = SEVERITY_RANK[self._current_profile.min_severity]
        finding_rank = SEVERITY_RANK[finding.severity]
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
            # R7's engine pre-walk populates _current_package_options
            # before Step 4's per-file walk; this snapshot is what R7 rules
            # consume via ctx.package_options. None when the pre-walk
            # early-returned (pool_file_names was empty).
            package_options=self._current_package_options,
            # D6c U1's cross-file pre-walk populates two views:
            # _current_directory_packages (per-package, R8's primary
            # view) + _current_directory_packages_by_dir (per-directory
            # inverted index, R8b's primary view). Both None when
            # root_files was empty. The dual-view design avoids R8b's
            # O(N²) scan over the per-package view.
            directory_packages=self._current_directory_packages,
            directory_packages_by_dir=self._current_directory_packages_by_dir,
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
            source_info_descriptors=self._current_source_info_descriptors,
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
            source_info_descriptors=self._current_source_info_descriptors,
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
            source_info_descriptors=self._current_source_info_descriptors,
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
            source_info_descriptors=self._current_source_info_descriptors,
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
            source_info_descriptors=self._current_source_info_descriptors,
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
