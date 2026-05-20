"""``options/field-behavior-consistent`` rule pack — D6d Unit 2.

Single specimen of the "value-validation" template family. Validates
well-formedness of declared ``(google.api.field_behavior)`` annotation
lists on proto fields. Anchored to https://google.aip.dev/203.

Three violation arms, each its own ``violation_kind`` so SARIF agent-
native consumers can discriminate by
``finding.params['violation_kind']`` without parsing the rendered
message text (see
[[dict-shaped-message-template-multi-arm-rule-violation-kind-2026-05-19]]).

- ``options/field-behavior-consistent/duplicate-value`` — the same
  FieldBehavior enum identifier appears 2+ times in the annotation
  list. One finding per duplicated value (NOT per duplicate
  occurrence), emitted in alphabetic-by-value order.
- ``options/field-behavior-consistent/unspecified-value`` — the
  zero value ``FIELD_BEHAVIOR_UNSPECIFIED`` appears in the list.
  AIP-203 forbids: "FIELD_BEHAVIOR_UNSPECIFIED must not be used".
- ``options/field-behavior-consistent/contradictory-pair`` — two
  values appear that are mutually exclusive under AIP-203 semantics.
  Curated set (5 pairs; inclusion criterion: per-value semantic
  guarantees are mutually exclusive under any valid AIP-203
  interpretation — no field can simultaneously be both):

  * ``(OPTIONAL, REQUIRED)`` — definitionally opposite.
  * ``(REQUIRED, OUTPUT_ONLY)`` — "user MUST provide" vs "server
    ignores user-provided values".
  * ``(INPUT_ONLY, OUTPUT_ONLY)`` — opposite directionality.
  * ``(IMMUTABLE, OUTPUT_ONLY)`` — IMMUTABLE permits create-time
    input; OUTPUT_ONLY forbids input always.
  * ``(IMMUTABLE, INPUT_ONLY)`` — IMMUTABLE means the value is
    visible in GET responses; INPUT_ONLY forbids responses.

  IDENTIFIER-based contradictions (e.g., ``(IDENTIFIER, OUTPUT_ONLY)``)
  are deliberately excluded from the curated set: AIP-203 says
  IDENTIFIER "conveys OUTPUT_ONLY in create contexts and IMMUTABLE
  in mutation contexts" — the contextual semantics make a hard
  contradiction claim harder to defend. Deferred to D6e+ pending
  evidence.

**Phase 0a (D6d U2) finding:** protoxy compile-FAILS on unknown enum
identifiers (``= REQURIED``) and on out-of-enum numeric literals
(``= 999``). The "INVALID identifier" and "numeric out-of-enum"
violation classes are therefore unreachable at the lint stage. The
only reachable "invalid"-like case is the explicit
``FIELD_BEHAVIOR_UNSPECIFIED`` identifier, which surfaces normally
because it's a valid enum value with numeric ``0``. The third arm is
named ``unspecified-value`` (not ``invalid-value``) to reflect this
narrowed scope. Future protobuf releases that surface unknown enum
numbers differently would extend this contract; the
``resolve_enum_value_for_comparison`` helper already returns the raw
integer for unknown-number cases.

**Extension-access path:** the rule re-uses U1's dynamic-pool re-
parse helpers from
:mod:`protokit.schema.lint._extension_access`
(``get_pool_bound_options_class`` +
``resolve_enum_value_for_comparison``) — the bootstrap-pool
``Extensions[]`` accessor raises ``KeyError`` on dynamic-pool
extension descriptors, so the re-parse workaround is mandatory.
When the user's compile set does NOT include
``google/api/field_behavior.proto``, ``pool.FindExtensionByName``
raises ``KeyError``; the rule emits a deduplicated
``LintRuntimeWarning(category="extension_unresolved")`` and skips
firing for that file.

**Dormancy (D6d U2):** the rule pack is module-imported but NOT
registered in ``BUILTIN_PACKS``. Registration ships in D6d U5
(delivery boundary) per
[[dormant-code-changelog-draft-staging-delivery-boundary-2026-05-17]].

**Profile placement:** ``severity=WARNING``, ``profiles=("default",)``
only. ``recommended``-profile users see ZERO new findings on D6d
upgrade per R6 of the D6d brainstorm — conservative-launch posture
matching D6b R6's leading-comment family. Promotion to
``recommended`` deferred to D6e+ pending corpus evidence.

**Severity profile dispatch:** the three violation arms share a
uniform ``WARNING`` severity, implemented as a dict-shaped
``_SEVERITIES`` (matching the dict-shaped ``_MESSAGE_TEMPLATES``,
per :meth:`LintRuleSpec.__post_init__`'s shape-pairing invariant —
``severity`` and ``message_template`` must both be scalar or both
be dict; mismatch raises ``TypeError`` at module import). All three
arms share ``WARNING`` for the conservative-launch posture; the
dict shape supports per-arm severity divergence in the future
without touching the rule body.

References:

- AIP-203: https://google.aip.dev/203
- googleapis source:
  https://github.com/googleapis/googleapis/blob/master/google/api/field_behavior.proto
- D6d brainstorm:
  ``docs/brainstorms/2026-05-19-d6d-option-aware-pack-expansion-requirements.md``
- D6d plan:
  ``docs/plans/2026-05-19-001-feat-d6d-option-aware-pack-expansion-plan.md``
- Dict-template precedent:
  ``src/protokit/schema/lint/rules/package.py`` (R8b
  ``_R8B_MESSAGE_TEMPLATES``).
"""

from __future__ import annotations

import weakref
from collections import Counter
from collections.abc import Callable
from typing import TYPE_CHECKING

from protokit.schema.lint._cli_utils import _safe_for_stderr
from protokit.schema.lint._extension_access import (
    get_pool_bound_options_class,
    resolve_enum_value_for_comparison,
)
from protokit.schema.lint.decorator import lint_rule
from protokit.schema.lint.model import (
    ElementKind,
    FieldLintContext,
    LintRuleError,
    LintRuntimeWarning,
    LintSeverity,
)

if TYPE_CHECKING:
    from protokit.schema.lint.engine import LintEngine

#: Per-finding parameter cap, mirroring the R7/R8 disciplines: each
#: ``params`` value is bounded so attacker-controlled identifier names
#: cannot inflate the rendered message size.
_PARAM_CAP = 500

#: Fully-qualified extension reference the rule resolves on the
#: descriptor pool. Pinned: the rule is bound to the canonical
#: googleapis extension name, NOT user-configurable. Users who want
#: rule-firing on a different extension write a ``custom/<suffix>``
#: rule via ``[[tool.protokit.lint.custom_annotation_rules]]`` (D6d
#: U1).
_FIELD_BEHAVIOR_EXTENSION: str = "google.api.field_behavior"

#: Fully-qualified options message the extension lives on.
_FIELD_OPTIONS_FULL_NAME: str = "google.protobuf.FieldOptions"

#: Rule_id constant — referenced from tests + the runtime warning
#: emission site so the string is single-sourced.
RULE_ID: str = "options/field-behavior-consistent"

#: Violation_kind arm constants.
_KIND_DUPLICATE: str = f"{RULE_ID}/duplicate-value"
_KIND_UNSPECIFIED: str = f"{RULE_ID}/unspecified-value"
_KIND_CONTRADICTORY: str = f"{RULE_ID}/contradictory-pair"

#: Dict-shaped ``message_template`` keyed by ``violation_kind``. Each
#: arm uses different placeholders, so the per-arm template carries
#: only the placeholders its arm populates. Pattern matches R8b's
#: dict-template precedent.
_MESSAGE_TEMPLATES: dict[str, str] = {
    _KIND_DUPLICATE: (
        'Field "{field_name}" has duplicate (google.api.field_behavior) '
        '= {value} entries.'
    ),
    _KIND_UNSPECIFIED: (
        'Field "{field_name}" has (google.api.field_behavior) = '
        '{value}; AIP-203 forbids FIELD_BEHAVIOR_UNSPECIFIED.'
    ),
    _KIND_CONTRADICTORY: (
        'Field "{field_name}" has contradictory '
        '(google.api.field_behavior) entries: {value_a} and {value_b}.'
    ),
}

#: Dict-shaped severity — the LintRuleSpec ``__post_init__`` requires
#: ``severity`` and ``message_template`` to share shape. All three
#: arms share ``WARNING`` (uniform-severity per-arm dict), matching
#: the conservative-launch posture committed in R6 of the D6d
#: brainstorm. Per-arm severity divergence is a deferred future
#: option — if downstream evidence emerges that ``unspecified-value``
#: deserves ``ERROR`` while contradictory pairs stay ``WARNING``, the
#: dict shape supports the split without touching the rule body.
_SEVERITIES: dict[str, LintSeverity] = {
    _KIND_DUPLICATE: LintSeverity.WARNING,
    _KIND_UNSPECIFIED: LintSeverity.WARNING,
    _KIND_CONTRADICTORY: LintSeverity.WARNING,
}

#: AIP-203-anchored contradictory pairs. Each pair is stored
#: alphabetically (``a < b``) so the emission ordering is independent
#: of proto source order. See module docstring for inclusion criteria.
_CONTRADICTORY_PAIRS: frozenset[tuple[str, str]] = frozenset(
    {
        ("OPTIONAL", "REQUIRED"),
        ("OUTPUT_ONLY", "REQUIRED"),
        ("INPUT_ONLY", "OUTPUT_ONLY"),
        ("IMMUTABLE", "OUTPUT_ONLY"),
        ("IMMUTABLE", "INPUT_ONLY"),
    }
)
# Structural enforcement of the alphabetic-storage convention — a
# non-alphabetic tuple (e.g., ("REQUIRED", "OPTIONAL")) would cause
# value_a/value_b to flip in emitted params depending on proto source
# order, breaking the order-invariance contract. Fires at module
# import time so a malformed addition fails CI immediately.
assert all(a < b for a, b in _CONTRADICTORY_PAIRS), (
    "_CONTRADICTORY_PAIRS tuples must be alphabetically sorted "
    "(a < b). Mis-ordered pairs flip value_a/value_b in emitted params."
)

#: The zero-value identifier the rule flags as ``unspecified-value``.
_UNSPECIFIED_VALUE: str = "FIELD_BEHAVIOR_UNSPECIFIED"

# Per-engine + per-run dedup map for unresolved-extension warnings.
# Keyed by engine instance (via ``WeakKeyDictionary`` so dedup state
# is collected when the engine is GC'd — no cross-engine leakage, no
# manual reset). Value is ``(runtime_warnings_list_id, dedup_set)``;
# ``id(engine._runtime_warnings)`` changes on every ``engine.run()``
# entry (the engine assigns a fresh list at engine.py:418), so a
# mismatched id signals a NEW run and the dedup set is reset
# automatically. This closes the cross-run dedup leak documented at
# ce:review COR-1 / ADV-1: without the per-run reset, a second
# ``engine.run()`` on the same engine would silently emit zero
# warnings even though the unresolved-extension condition still
# holds for the second run.
_UNRESOLVED_SEEN: weakref.WeakKeyDictionary[LintEngine, tuple[int, set[tuple[str, str]]]] = (
    weakref.WeakKeyDictionary()
)


def _engine_for_ctx(ctx: FieldLintContext) -> LintEngine:
    """Return the active ``LintEngine`` for a given context.

    ``FieldLintContext`` doesn't expose a public ``engine`` attribute,
    but the engine threads itself in via ``ctx._emit_fn``, which is
    the engine's bound ``_emit`` method. The bound method's
    ``__self__`` IS the active engine instance — the cleanest path
    for built-in rules that need to enqueue runtime warnings without
    requiring a public surface change on ``LintContext``.

    Raises:
        LintRuleError: if ``ctx._emit_fn`` is not a bound method (the
            engine's context-construction shape changed). Raising
            ``LintRuleError`` (NOT bare ``RuntimeError``) routes the
            failure through ``_RULE_EXCEPTION_TUPLE`` so the engine
            records a ``rule_exception`` runtime warning and continues
            walking remaining files rather than hard-crashing
            ``engine.run()``. Failing loudly via the rule_exception
            channel is the project's discipline for structural-env
            failures inside rule callables.
    """
    emit_fn = ctx._emit_fn
    engine = getattr(emit_fn, "__self__", None)
    if engine is None:
        raise LintRuleError(
            "options/field-behavior-consistent could not resolve the "
            "active LintEngine through ctx._emit_fn. The context shape "
            "changed; update _engine_for_ctx accordingly."
        )
    return engine  # type: ignore[no-any-return]


def _emit_unresolved_extension(ctx: FieldLintContext) -> None:
    """Emit a deduplicated ``extension_unresolved`` runtime warning.

    Matches the U1 synthetic-rule emission shape but uses the new
    ``"extension_unresolved"`` Literal value (D6d U2 — engine-emitted,
    for built-in option-aware rules whose depended-on extension is
    absent from the compile set).

    Dedup is keyed by ``(rule_id, file_name)`` within a per-engine,
    per-run set: the value held in :data:`_UNRESOLVED_SEEN` is the
    tuple ``(id(engine._runtime_warnings), dedup_set)``. On each
    ``engine.run()`` entry the engine assigns a fresh list to
    ``_runtime_warnings`` (engine.py:418), so a stale tuple whose
    ``id`` no longer matches the engine's current list signals a NEW
    run, and the dedup set is reset. This handles both cross-engine
    isolation (via ``WeakKeyDictionary``) and cross-run isolation
    on the same engine (via the id-mismatch detection) without
    needing a public engine-side reset hook.
    """
    engine = _engine_for_ctx(ctx)
    current_id = id(engine._runtime_warnings)
    state = _UNRESOLVED_SEEN.get(engine)
    if state is None or state[0] != current_id:
        # New engine (no prior state) OR same engine but fresh
        # _runtime_warnings list (= new run() call).
        seen: set[tuple[str, str]] = set()
        _UNRESOLVED_SEEN[engine] = (current_id, seen)
    else:
        seen = state[1]
    file_name = ctx.file.name
    dedup_key = (RULE_ID, file_name)
    if dedup_key in seen:
        return
    seen.add(dedup_key)
    safe_rule_id = _safe_for_stderr(RULE_ID)[:_PARAM_CAP]
    safe_option = _safe_for_stderr(_FIELD_BEHAVIOR_EXTENSION)[:_PARAM_CAP]
    safe_file = _safe_for_stderr(file_name)[:_PARAM_CAP]
    engine._runtime_warnings.append(
        LintRuntimeWarning(
            category="extension_unresolved",
            rule_id=safe_rule_id,
            message=(
                f"rule {safe_rule_id!r} skipped on file {safe_file!r}: "
                f"extension {safe_option!r} is not registered in the "
                f"compile pool"
            ),
        ),
    )


@lint_rule(
    rule_id=RULE_ID,
    severity=_SEVERITIES,
    profiles=("default",),
    element=ElementKind.FIELD,
    message_template=_MESSAGE_TEMPLATES,
    source_spec="https://google.aip.dev/203",
)
def check_field_behavior_consistent(ctx: FieldLintContext) -> None:
    """Fire on duplicate, unspecified, or contradictory FieldBehavior values.

    Walks the field's ``(google.api.field_behavior)`` repeated
    extension. If the extension is not registered in the compile
    pool (the user didn't include ``google/api/field_behavior.proto``),
    emits ``LintRuntimeWarning(category="extension_unresolved")`` and
    skips. Otherwise, reads all annotated values, normalizes enum
    numbers to identifier-string names via the U1
    ``resolve_enum_value_for_comparison`` helper, then runs three
    checks emitted in alphabetic-by-violation_kind order:

    1. ``contradictory-pair`` (c) — any of the 5 curated pairs
       both present.
    2. ``duplicate-value`` (d) — any value present 2+ times.
    3. ``unspecified-value`` (u) — ``FIELD_BEHAVIOR_UNSPECIFIED``
       present.

    Each finding's ``params`` includes ``field_name`` plus arm-
    specific keys (``value`` for duplicate/unspecified; ``value_a``,
    ``value_b`` for contradictory-pair). All identifier strings are
    bounded by ``_PARAM_CAP`` (500 chars) per the R7/R8 attacker-
    string-bound discipline.
    """
    pool = ctx.pool
    try:
        ext_desc = pool.FindExtensionByName(_FIELD_BEHAVIOR_EXTENSION)
    except KeyError:
        _emit_unresolved_extension(ctx)
        return

    options_cls = get_pool_bound_options_class(pool, _FIELD_OPTIONS_FULL_NAME)
    if options_cls is None:
        # Pool missing ``descriptor.proto``-derived FieldOptions class.
        # Non-actionable env condition; skip silently (matches U1
        # synthetic-rule discipline).
        return

    parsed = options_cls()
    parsed.MergeFromString(ctx.field.GetOptions().SerializeToString())
    raw_values = list(parsed.Extensions[ext_desc])
    if not raw_values:
        return

    names = [resolve_enum_value_for_comparison(ext_desc, v) for v in raw_values]
    safe_field = _safe_for_stderr(ctx.field.name)[:_PARAM_CAP]

    # 1. contradictory-pair — alphabetic-by-(value_a, value_b) ordering.
    fired_pairs: list[tuple[str, str]] = []
    present: set[str] = {n for n in names if isinstance(n, str)}
    for pair in _CONTRADICTORY_PAIRS:
        a, b = pair  # already alphabetic-sorted at construction
        if a in present and b in present:
            fired_pairs.append((a, b))
    fired_pairs.sort()
    for value_a, value_b in fired_pairs:
        safe_a = _safe_for_stderr(value_a)[:_PARAM_CAP]
        safe_b = _safe_for_stderr(value_b)[:_PARAM_CAP]
        ctx.emit(
            violation_kind=_KIND_CONTRADICTORY,
            params={
                "field_name": safe_field,
                "value_a": safe_a,
                "value_b": safe_b,
            },
        )

    # 2. duplicate-value — one finding per duplicated value (NOT per
    # duplicate occurrence). Alphabetic-by-value ordering.
    name_counts = Counter(n for n in names if isinstance(n, str))
    duplicates = sorted(n for n, count in name_counts.items() if count > 1)
    for dup in duplicates:
        safe_dup = _safe_for_stderr(dup)[:_PARAM_CAP]
        ctx.emit(
            violation_kind=_KIND_DUPLICATE,
            params={
                "field_name": safe_field,
                "value": safe_dup,
            },
        )

    # 3. unspecified-value — single finding when present.
    if _UNSPECIFIED_VALUE in present:
        safe_unspec = _safe_for_stderr(_UNSPECIFIED_VALUE)[:_PARAM_CAP]
        ctx.emit(
            violation_kind=_KIND_UNSPECIFIED,
            params={
                "field_name": safe_field,
                "value": safe_unspec,
            },
        )


#: Pack tuple — exposes the single rule for ``LintEngine.load_rule_pack``.
RULES: tuple[Callable[..., None], ...] = (check_field_behavior_consistent,)
