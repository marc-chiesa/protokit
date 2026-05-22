"""``field`` rule pack — field-level structural rules.

Currently ships one rule:

- ``field/not-required`` (buf:FIELD_NOT_REQUIRED) — fires when a
  proto2 field is declared ``required``. Proto2-only;
  ``recommended`` + ``default`` profiles see ZERO findings from
  this rule (D6e KD-5 + KD-2: proto2-specific strictness ships
  in opt-in ``proto2-strict`` profile only per the inverted UX
  philosophy at KD-1).

D6e U1+U2 (0.6.0) introduces the ``field`` pack as the namespace
anchor for future field-level proto2-strict rules per KD-11 (the
per-syntax-version profile pattern). Future candidates include
``field/no-group-syntax`` (proto2-only ``group`` construct),
``field/no-explicit-default`` (proto2's ``default = X``), and
``field/packed-repeated-primitive`` (proto2 packed annotation).
None of those ship in D6e.

Phase 0 EV-2 falsification (2026-05-22)
---------------------------------------

The brainstorm + plan originally framed a "documented extend-block
divergence" where buf v1.69.0 would fire ``FIELD_NOT_REQUIRED`` on
extend-block ``required`` fields while protokit (whose engine
walker at ``engine.py:841-916`` does not iterate
``fd.extensions_by_name`` or ``Message.extensions_by_name``) would
not. **Phase 0 of U2 empirically falsified this premise.** Both
buf v1.69.0 AND protokit's own compiler (protoxy) reject
``required`` extension fields at the parse layer with
``Failure: input image: proto: extension field ... has an invalid
cardinality: 2``. The protobuf spec disallows LABEL_REQUIRED for
extension fields; the construct cannot be compiled, so no
rule-level divergence exists. The engine walker's non-iteration
of ``extensions_by_name`` is architecturally real but operationally
moot. No four-site divergence documentation, no
``_PARITY_EXCEPTIONS`` entry, no walker-extension backlog —
``field/not-required`` ships with clean buf-parity. See
``docs/solutions/best-practices/phase-0-empirical-verification-falsifies-brainstorm-assumption-2026-05-22.md``
for the institutional lesson.

The CopyToProto round-trip pattern (mirrors ``file.py``) is used
to read ``fdp.syntax`` because ``FileDescriptor.syntax`` is not
exposed on the upb backend's runtime descriptor (see
``docs/solutions/best-practices/copytoproto-round-trip-for-proto-form-only-descriptor-fields-2026-05-13.md``).

References:
- buf BASIC rule catalog (parity target named via
  ``source_spec="buf:FIELD_NOT_REQUIRED"``).
- protokit-lint D6e plan, U2.
- SUPERSEDED brainstorm `docs/brainstorms/2026-05-20-d6d-u3-field-not-required-requirements.md`
  (UR-6 rule body bound verbatim; severity/profile decisions
  superseded by D6e KD-5).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from google.protobuf import descriptor as proto_descriptor
from google.protobuf import descriptor_pb2

from protokit.schema.lint.decorator import lint_rule
from protokit.schema.lint.model import ElementKind, LintSeverity

if TYPE_CHECKING:
    from protokit.schema.lint.model import FieldLintContext


@lint_rule(
    rule_id="field/not-required",
    severity=LintSeverity.ERROR,
    profiles=("proto2-strict",),
    element=ElementKind.FIELD,
    message_template=(
        "Field {field_name!r} is declared ``required`` in a proto2 "
        "message; the ``required`` label is a known footgun (cannot "
        "be safely removed once published) — declare as ``optional`` "
        "and validate at the application layer"
    ),
    source_spec="buf:FIELD_NOT_REQUIRED",
)
def check_field_not_required(ctx: FieldLintContext) -> None:
    """Fire on proto2 ``required`` fields (excludes proto3 + editions).

    The rule applies only to files with empty ``fdp.syntax`` — the
    protobuf compiler emits ``""`` for proto2 (both no-statement
    and explicit ``syntax = "proto2";``) and a non-empty string
    (``"proto3"`` or ``"editions"``) for the post-proto2 syntaxes.
    The early-return on non-proto2 syntax keeps the rule's blast
    radius bounded to the targeted population.

    Group-typed required fields (EV-3 binding): proto2 groups
    surface in the descriptor as a regular field with LABEL_REQUIRED
    and a lowercased name derived from the group declaration (e.g.,
    ``required group RequiredGroup`` → field name ``requiredgroup``).
    The rule fires on the implicit field; buf v1.69.0 does the
    same per Phase 0 verification.

    Extend-block required fields (EV-2 falsification): both buf
    v1.69.0 and protokit's compiler reject ``required`` extension
    fields at parse layer ("invalid cardinality: 2"). The construct
    cannot be compiled, so the engine walker's non-iteration of
    extensions is operationally moot — the rule cannot encounter
    a ``required`` extension at runtime because none can exist in
    a valid descriptor set. See module docstring for the full
    falsification story.
    """
    fdp = descriptor_pb2.FileDescriptorProto()
    ctx.file.CopyToProto(fdp)
    # Skip non-proto2 (proto3 emits "proto3"; editions emits "editions"):
    if fdp.syntax != "":
        return
    if ctx.field.label == proto_descriptor.FieldDescriptor.LABEL_REQUIRED:
        ctx.emit(
            violation_kind="field/not-required",
            params={"field_name": ctx.field.name},
        )


# Module-level RULES tuple read by ``LintEngine.load_rule_pack``.
RULES: tuple[Callable[..., None], ...] = (
    check_field_not_required,
)
