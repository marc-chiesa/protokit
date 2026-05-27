"""Synthetic ``custom/<suffix>`` rule loader.

Materializes user-declared ``[[tool.protokit.lint.custom_annotation_rules]]``
entries into a synthetic ``ModuleType`` exposing a ``RULES`` tuple of
closures (per-entry, per-``ElementKind``). The synthetic module is fed
to :meth:`protokit.schema.lint.engine.LintEngine.load_rule_pack` to
register the closures into the engine's ``_loaded_specs`` dict through
the same code path BUILTIN_PACKS modules travel.

The user-facing contract is the synthetic ``rule_id`` ``custom/<suffix>``
that surfaces in finding output exactly like a built-in rule_id — no
machine-readable distinction beyond the ``custom/`` namespace prefix
(invariant: ``BUILTIN_PACKS`` MUST NEVER ship a ``custom/*``
rule_id).

**Extension-resolution model** (per the Phase 0 empirical verification
that landed alongside this loader, 2026-05-19).
The naive ``protokit.options.get_option_value`` helper does NOT surface
custom-extension values when the extension is registered through a
``protoxy``-built ``DescriptorPool`` (rather than via a generated
``_pb2`` module). The data is stored in the options message's
serialized bytes, but ``GetOptions()`` returns a bootstrap-pool-bound
options instance whose ``Extensions[]`` accessor raises ``KeyError``
("Extension doesn't match") for the dynamic-pool extension descriptor.

The workaround used here:

1. Look up the extension descriptor via ``pool.FindExtensionByName(option)``.
   If ``KeyError`` is raised, emit a runtime warning
   (category ``custom_annotation_extension_unresolved``) and skip.
2. Look up the options descriptor for the element kind
   (``MethodOptions`` / ``FieldOptions`` / ``FileOptions`` / ...) in
   the SAME pool — done by
   :func:`protokit.schema.lint._extension_access.get_pool_bound_options_class`.
3. Build a pool-bound options message class via
   ``google.protobuf.message_factory.GetMessageClass(options_desc)``
   (protobuf 5.26+; fall back to
   ``MessageFactory(pool=pool).GetPrototype(options_desc)`` for
   4.21–5.25 compatibility) — same helper.
4. Re-parse the serialized bytes from
   ``descriptor.GetOptions().SerializeToString()`` into the pool-
   bound class. ``parsed.HasExtension(ext_desc)`` and
   ``parsed.Extensions[ext_desc]`` now work correctly with proto2
   presence semantics on the options message.

Steps 2-3 (the pool-bound class lookup) and the enum-int → identifier
normalization live in :mod:`protokit.schema.lint._extension_access`
so built-in option-aware rules (such as
``options/field-behavior-consistent``) reuse the same code path
without depending on private symbols from this module.

For enum-typed extensions, the runtime value is the enum number
(int). The closure translates to the identifier string via
``ext_desc.enum_type.values_by_number[value].name`` so it can be
compared against ``allowed_values`` written as identifier strings
(per the R2 contract).

**Closure capture discipline.** Closures bind per-entry state via
factory functions to avoid the loop-variable capture-by-reference
footgun. Each synthetic rule has its own state (option name,
allowed_values, severity, dedup set) bound by the factory's argument
frame, not by the enclosing loop.

**Dedup of unresolved-extension warnings.** The
``custom_annotation_extension_unresolved`` warning emits at most once
per ``(rule_id, file_name)`` tuple even though the closure runs per
descriptor of the configured ElementKind. Dedup state lives in the
module-level :data:`_UNRESOLVED_SEEN` :class:`weakref.WeakKeyDictionary`
keyed by the active :class:`LintEngine`. The value tracks
``(id(engine._runtime_warnings), seen_set)``; because
``engine.run()`` assigns a fresh ``_runtime_warnings`` list on each
entry, an id-mismatch signals a NEW run and the dedup set resets
automatically. This mirrors the pattern in
``protokit.schema.lint.rules.options.field_behavior`` and closes the
cross-run dedup leak that the original closure-captured-set pattern
carried (see the matching per-engine-per-run state learning under
``docs/solutions/``). The CLI is unaffected today (one
``engine.run()`` per process), but long-lived runtimes (MCP / IDE
integrations) that recycle engines across sessions would otherwise
observe silent dedup leakage (tracked in TODOS.md backlog).

**Synthetic module name.** ``_SYNTHETIC_MODULE_NAME`` is a stable
identifier; the ``LintEngine.load_rule_pack`` idempotency guard at
``engine.py:303`` short-circuits a second load on the same engine
instance. The CLI creates a fresh engine per invocation so this is
correct. Long-lived engines would observe stale rule registration on
config changes — a known long-lived-runtime concern (tracked in
TODOS.md backlog).

References:

- See the project's design notes for the option-aware pack-expansion
  plan and the Phase 0 re-parse-pattern rationale.
- ``custom/`` namespace invariant enforced by
  ``tests/schema/lint/test_no_builtin_rule_uses_custom_prefix.py``.
"""

from __future__ import annotations

import weakref
from collections.abc import Sequence
from types import ModuleType
from typing import TYPE_CHECKING, Any

from protokit.schema.lint._cli_utils import _safe_for_stderr
from protokit.schema.lint._extension_access import (
    get_pool_bound_options_class,
    resolve_enum_value_for_comparison,
)
from protokit.schema.lint.model import (
    ElementKind,
    LintRuleSpec,
    LintRuntimeWarning,
    LintSeverity,
)

if TYPE_CHECKING:
    from protokit.schema.lint._config import CustomAnnotationRuleSpec
    from protokit.schema.lint.engine import LintEngine


#: Synthetic module name. See module docstring for the
#: idempotency / single-shot rationale.
_SYNTHETIC_MODULE_NAME: str = "protokit_lint_synthetic_custom_annotations"


# Per-engine + per-run dedup map for unresolved-extension warnings.
# Mirrors the pattern in
# ``protokit.schema.lint.rules.options.field_behavior`` — keyed by
# engine via ``WeakKeyDictionary`` so dedup state is collected when
# the engine is GC'd. Value is ``(id(engine._runtime_warnings),
# dedup_set)``: the id changes on every ``engine.run()`` entry (the
# engine assigns a fresh list at ``engine.py``'s run path), so a
# mismatched id signals a NEW run and the dedup set is reset
# automatically. This closes the cross-run dedup leak that the
# original closure-captured-set pattern carried (see the matching
# per-engine-per-run-state learning under ``docs/solutions/``):
# without the per-run reset, a second ``engine.run()`` on the same
# engine would silently emit zero warnings even though the
# unresolved-extension condition still holds. The CLI is unaffected
# today (one ``engine.run()`` per process), but long-lived runtimes
# (MCP / IDE integrations) that recycle engines across sessions would
# hit the leak without this discipline (tracked in TODOS.md backlog).
_UNRESOLVED_SEEN: weakref.WeakKeyDictionary[LintEngine, tuple[int, set[tuple[str, str]]]] = (
    weakref.WeakKeyDictionary()
)


def _dedup_seen_for_run(engine: LintEngine) -> set[tuple[str, str]]:
    """Return the dedup set scoped to the engine's current ``run()``.

    Resets the set whenever ``id(engine._runtime_warnings)`` changes
    (i.e., a fresh ``run()`` started). Same id-tracking discipline as
    ``options.field_behavior._emit_unresolved_extension``.
    """
    current_id = id(engine._runtime_warnings)
    state = _UNRESOLVED_SEEN.get(engine)
    if state is None or state[0] != current_id:
        seen: set[tuple[str, str]] = set()
        _UNRESOLVED_SEEN[engine] = (current_id, seen)
        return seen
    return state[1]


#: Per-ElementKind metadata for the synthetic closure body.
#:
#: Maps the kind to a ``(ctx_attr, options_full_name)`` pair where
#: ``ctx_attr`` is the name of the descriptor attribute on the lint
#: context (e.g., ``"field"`` for FieldLintContext) and
#: ``options_full_name`` is the fully-qualified options message name
#: used to resolve a pool-bound options class. The lookup is centralized
#: so the closure body stays kind-uniform (per the Phase 0 finding
#: that landed alongside this loader).
_KIND_DESCRIPTOR_TABLE: dict[ElementKind, tuple[str, str]] = {
    ElementKind.FILE: ("file", "google.protobuf.FileOptions"),
    ElementKind.SERVICE: ("service", "google.protobuf.ServiceOptions"),
    ElementKind.METHOD: ("method", "google.protobuf.MethodOptions"),
    ElementKind.ENUM: ("enum", "google.protobuf.EnumOptions"),
    ElementKind.ENUM_VALUE: ("value", "google.protobuf.EnumValueOptions"),
    ElementKind.MESSAGE: ("message", "google.protobuf.MessageOptions"),
    ElementKind.FIELD: ("field", "google.protobuf.FieldOptions"),
    ElementKind.ONEOF: ("oneof", "google.protobuf.OneofOptions"),
}


def _make_synthetic_closure(
    spec: CustomAnnotationRuleSpec,
    kind: ElementKind,
    engine: LintEngine,
) -> Any:
    """Factory: build one synthetic-rule closure for ``(spec, kind)``.

    The per-entry state (``spec``, ``kind``) binds via the factory's
    argument frame — NOT via the enclosing loop's variable. This
    avoids the classic Python loop-variable capture-by-reference
    footgun where two distinct entries would otherwise share the last
    entry's bindings.

    The closure body:

    1. Resolves the extension descriptor via
       ``ctx.pool.FindExtensionByName(spec.option)``. On ``KeyError``,
       emits a deduplicated
       ``custom_annotation_extension_unresolved`` runtime warning and
       returns. Dedup state lives in the module-level
       :data:`_UNRESOLVED_SEEN` :class:`WeakKeyDictionary` keyed by
       engine + a per-run id, so the warning re-fires on a fresh
       ``engine.run()`` call (closes the original cross-run leak;
       see the matching per-engine-per-run-state learning under
       ``docs/solutions/``).
    2. Resolves the pool-bound options class. On a missing
       ``descriptor.proto`` pool entry (rare; minimal compile sets),
       silently returns (no warning — this is a non-actionable env
       condition, not a user config error).
    3. Re-parses the serialized options bytes through the pool-bound
       class so ``HasExtension`` and ``Extensions[]`` work for the
       dynamic-pool extension descriptor.
    4. Presence check: fires when ``HasExtension(ext_desc)`` is
       ``False`` (extension absent from this descriptor).
    5. Value check (only when ``allowed_values`` is configured):
       fires when the resolved value (with enum-int→identifier
       translation) is not in the allowed set.

    Args:
        spec: The validated pyproject entry.
        kind: The ElementKind this closure targets (one of
            ``spec.element_kinds``).
        engine: The active ``LintEngine`` — used to append runtime
            warnings to ``engine._runtime_warnings``. The reference
            is captured per-closure; long-lived engines must rebuild
            the synthetic module per config change.

    Returns:
        A function ``closure(ctx) -> None`` with an attached
        ``_lint_spec: LintRuleSpec`` matching the synthetic
        ``custom/<suffix>`` rule_id + the targeted ElementKind.
    """
    ctx_attr, options_full_name = _KIND_DESCRIPTOR_TABLE[kind]
    rule_id = spec.rule_id
    option = spec.option
    allowed_values = spec.allowed_values

    def closure(ctx: Any) -> None:
        pool = ctx.pool
        try:
            ext_desc = pool.FindExtensionByName(option)
        except KeyError:
            file_name = ctx.file.name
            seen = _dedup_seen_for_run(engine)
            dedup_key = (rule_id, file_name)
            if dedup_key not in seen:
                seen.add(dedup_key)
                safe_rule_id = _safe_for_stderr(rule_id)
                safe_option = _safe_for_stderr(option)
                safe_file = _safe_for_stderr(file_name)
                engine._runtime_warnings.append(
                    LintRuntimeWarning(
                        category="custom_annotation_extension_unresolved",
                        rule_id=safe_rule_id,
                        message=(
                            f"synthetic rule {safe_rule_id!r} skipped on "
                            f"file {safe_file!r}: extension {safe_option!r} "
                            f"is not registered in the compile pool"
                        ),
                    ),
                )
            return

        options_cls = get_pool_bound_options_class(pool, options_full_name)
        if options_cls is None:
            # Pool missing ``descriptor.proto``-derived options class.
            # Skip silently — non-actionable env condition.
            return

        descriptor = getattr(ctx, ctx_attr)
        raw_options = descriptor.GetOptions()
        parsed = options_cls()
        parsed.MergeFromString(raw_options.SerializeToString())

        if not parsed.HasExtension(ext_desc):
            # Presence violation. Compose a violation_kind that lets
            # agent-native consumers discriminate "absent" from
            # "value-mismatch" without parsing the message_template.
            ctx.emit(
                violation_kind="custom-annotation-absent",
                params={
                    "rule_id": rule_id,
                    "option": option,
                },
            )
            return

        if allowed_values is None:
            # Presence-only rule; nothing more to check.
            return

        raw_value = parsed.Extensions[ext_desc]
        compared = resolve_enum_value_for_comparison(ext_desc, raw_value)
        if compared in allowed_values:
            return
        # Value-mismatch violation. Stringify ``compared`` for the
        # ``actual_value`` param so the message_template's
        # ``{actual_value}`` slot interpolates cleanly across str /
        # int / bool / enum-identifier values.
        ctx.emit(
            violation_kind="custom-annotation-value-mismatch",
            params={
                "rule_id": rule_id,
                "option": option,
                "actual_value": str(compared),
            },
        )

    # Build the message_template as a dict because the closure emits
    # two violation_kind values. Each template uses ``{rule_id}`` /
    # ``{option}`` (presence) plus ``{actual_value}`` (mismatch).
    message_template: dict[str, str] = {
        "custom-annotation-absent": (
            "Custom annotation {option} is missing "
            "(rule {rule_id})."
        ),
        "custom-annotation-value-mismatch": (
            "Custom annotation {option} has value {actual_value} which is "
            "not in the configured allowed_values "
            "(rule {rule_id})."
        ),
    }
    # Severity dict must share shape with the message_template (per
    # LintRuleSpec.__post_init__ invariant). Both kinds carry the same
    # configured severity since the user can only set one ``severity``
    # per entry.
    severity_map: dict[str, LintSeverity] = {
        "custom-annotation-absent": spec.severity,
        "custom-annotation-value-mismatch": spec.severity,
    }
    closure._lint_spec = LintRuleSpec(  # type: ignore[attr-defined]
        rule_id=rule_id,
        severity=severity_map,
        # Multiple profiles intentionally — synthetic rules are
        # always-on when configured. The composed-profile
        # augmentation in cli.py unions the synthetic rule_ids into
        # whichever profile the user selected, so this profile tuple
        # is documentary; LintProfile.from_pack(synthetic_module,
        # name) would derive the rule under any name that matches.
        profiles=("recommended", "default", "essentials"),
        source_spec="protokit:custom-annotation",
        element=kind,
        message_template=message_template,
        fn=closure,
    )
    return closure


def build_synthetic_module(
    specs: Sequence[CustomAnnotationRuleSpec],
    engine: LintEngine,
) -> ModuleType | None:
    """Construct a synthetic ``ModuleType`` exposing ``custom/<suffix>`` rules.

    Returns ``None`` when ``specs`` is empty — the caller (cli.py)
    short-circuits the synthetic-rule load path so the engine sees
    BUILTIN_PACKS and user packs only, matching the pre-custom-rule
    behavior byte-for-byte for the zero-config case.

    Each spec produces ``len(spec.element_kinds)`` closures (one per
    declared kind, all sharing the same ``rule_id``). The synthetic
    module's ``RULES`` tuple lists every closure in entry-insertion
    order, then by ``ElementKind`` declaration order within each entry
    — this matches the engine's expectation of a flat tuple and keeps
    the registration order deterministic.

    The returned module is fresh (constructed via ``ModuleType(name)``;
    NOT registered into ``sys.modules`` because the engine reads
    ``module.RULES`` directly and the module is consumed once at
    ``engine.load_rule_pack(synthetic_module)`` time).

    **Multi-kind ``rule_id`` collision pitfall.** Two closures sharing
    the same ``rule_id`` would normally trip
    :exc:`LintEngine.load_rule_pack`'s intra-pack collision detection.
    We verified empirically that
    ``LintEngine._loaded_specs`` is keyed by ``rule_id`` alone, so
    duplicating a key collides at the staging step
    (``engine.py:323-331``). To preserve multi-kind support, the
    synthetic module wraps each rule_id's closures together: instead
    of N entries in ``RULES`` with the same ``rule_id``, the module
    exposes ONE multi-kind closure per ``rule_id`` that dispatches
    internally on ``ctx`` type. The wrapper's ``_lint_spec`` declares
    ``element=ElementKind.FIELD`` arbitrarily; the wrapper's body
    inspects ``ctx`` and runs the kind-appropriate inner closure.

    **Concrete shape.** For a single-kind entry, the wrapper just
    returns the inner closure unchanged (one entry → one closure → one
    spec → one ``RULES`` slot). For a multi-kind entry, the wrapper
    holds N inner closures and dispatches on ``ctx.__class__``. The
    spec attached to the wrapper uses a multi-kind shape only when
    needed; the engine's per-kind dispatcher
    (``LintEngine._dispatch_file``) filters by ``spec.element``, so
    multi-kind dispatch requires registering one spec per ElementKind.

    The simplest correct design: one inner closure per (entry, kind),
    each with its own kind-specific spec. The engine's load_rule_pack
    rejects duplicate ``rule_id``s within a pack, so we synthesize
    distinct internal keys by appending the kind value to the spec's
    rule_id WHEN there are multiple kinds, surfacing them through a
    public-id mapping:

    * single-kind entry: one closure, ``rule_id="custom/<suffix>"``
    * multi-kind entry: N closures, ``rule_id="custom/<suffix>"`` —
      the engine rejects duplicate keys, so we route multi-kind
      entries through ``rule_id="custom/<suffix>"`` only for the
      FIRST kind, then ``custom/<suffix>__<kind>`` internally for the
      remaining kinds.

    Args:
        specs: Validated entries from
            ``ResolvedLintConfig.custom_annotation_rules``.
        engine: The active ``LintEngine`` instance. Captured by every
            closure for ``_runtime_warnings`` appends.

    Returns:
        A fresh ``ModuleType`` with a ``RULES`` tuple, or ``None``
        when ``specs`` is empty.
    """
    if not specs:
        return None

    module = ModuleType(_SYNTHETIC_MODULE_NAME)
    rules: list[Any] = []

    # Dedup state for the unresolved-extension warning lives in the
    # module-level :data:`_UNRESOLVED_SEEN` WeakKeyDictionary; keyed by
    # engine + per-run id, so cross-engine + cross-run isolation is
    # automatic. No per-spec set allocation needed.
    for spec in specs:
        for kind_index, kind in enumerate(spec.element_kinds):
            closure = _make_synthetic_closure(
                spec=spec,
                kind=kind,
                engine=engine,
            )
            # Multi-kind entries register N closures with the same
            # rule_id. The engine's intra-pack dedup keys by
            # spec.rule_id, so directly appending all closures would
            # raise DuplicateRuleError. We mint a kind-disambiguated
            # rule_id for closures past the first kind, EXPOSING the
            # public rule_id via the spec.message_template prefix and
            # documenting that multi-kind entries materialize one
            # synthetic rule_id per declared kind:
            #   spec.element_kinds=["field", "method"] →
            #     rule_id 0: "custom/<suffix>"           on FIELD
            #     rule_id 1: "custom/<suffix>__method"   on METHOD
            # Single-kind entries (the common case in the worked
            # example) avoid the suffix entirely. The internal
            # mangling stays hidden from the public R10 contract by
            # virtue of the public-rule_id-only being THE registered
            # name; the suffix variant is an INTERNAL detail surfaced
            # only in lint output when the user configured multi-kind.
            if kind_index > 0:
                # Disambiguate the internal rule_id so engine staging
                # accepts the closure. The public-facing surface
                # documents this shape (per the docstring above).
                mangled_id = f"{spec.rule_id}__{kind.value}"
                existing_spec = closure._lint_spec
                # Rebuild the LintRuleSpec with the mangled id. The
                # severity dict and message_template dict carry over
                # unchanged (R10 finding output presents the mangled
                # rule_id; users see it in --format=json output).
                closure._lint_spec = LintRuleSpec(
                    rule_id=mangled_id,
                    severity=existing_spec.severity,
                    profiles=existing_spec.profiles,
                    source_spec=existing_spec.source_spec,
                    element=existing_spec.element,
                    message_template=existing_spec.message_template,
                    fn=closure,
                )
            rules.append(closure)

    module.RULES = tuple(rules)  # type: ignore[attr-defined]
    return module


def synthetic_rule_ids(
    specs: Sequence[CustomAnnotationRuleSpec],
) -> frozenset[str]:
    """Return every ``rule_id`` (including kind-mangled forms) for ``specs``.

    Mirrors the rule_ids the synthetic module's RULES tuple would
    register. Used by the CLI's composed-profile augmentation step
    (cli.py): the augmentation unions these ids into
    ``composed_profile.rule_ids`` so the engine's profile filter
    activates the synthetic closures.

    For a single-kind entry, returns ``{f"custom/{suffix}"}``. For a
    multi-kind entry, returns
    ``{f"custom/{suffix}", f"custom/{suffix}__<kind>", ...}`` per the
    multi-kind mangling discipline documented in
    :func:`build_synthetic_module`.

    Args:
        specs: Validated entries.

    Returns:
        A frozenset of synthetic rule_ids; empty when ``specs`` is empty.
    """
    ids: set[str] = set()
    for spec in specs:
        for kind_index, kind in enumerate(spec.element_kinds):
            if kind_index == 0:
                ids.add(spec.rule_id)
            else:
                ids.add(f"{spec.rule_id}__{kind.value}")
    return frozenset(ids)
