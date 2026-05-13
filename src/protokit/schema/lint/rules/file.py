"""``file`` rule pack — file-level structural rules.

Currently ships one rule:

- ``file/syntax-specified`` (buf:SYNTAX_SPECIFIED) — fires when
  the file's resolved syntax is not ``"proto3"``. **Known buf-
  parity divergence**: buf's own SYNTAX_SPECIFIED rule fires only
  when the literal ``syntax = "...";`` declaration is missing
  from the .proto source. Protokit's rule operates on descriptor
  output, where the protobuf compiler emits ``fdp.syntax == ""``
  for BOTH "no syntax statement at all" AND ``syntax = "proto2";``
  files — the descriptor cannot distinguish the two cases.
  Protokit therefore fires on every proto2 file regardless of
  whether the syntax statement was explicit. This is stricter
  than buf and intentionally nudges users toward proto3; users
  with intentional proto2 codebases can demote the rule via
  ``[tool.protokit.lint.severities]`` (D6a R9a, U2).

The CopyToProto round-trip pattern is used here because
``FileDescriptor.syntax`` is not exposed on the upb backend's
runtime descriptor (see
``docs/solutions/best-practices/copytoproto-round-trip-for-proto-form-only-descriptor-fields-2026-05-13.md``).
Reading ``fdp.syntax`` after ``ctx.file.CopyToProto(fdp)`` is the
documented, stable, backend-agnostic path.

Module shape mirrors the other D6a rule packs.

References:
- buf BASIC rule catalog (parity targets named per-rule via
  ``source_spec="buf:<RULE_ID>"``).
- protokit-lint D6a plan, Unit 6.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from google.protobuf import descriptor_pb2

from protokit.schema.lint.decorator import lint_rule
from protokit.schema.lint.model import ElementKind, LintSeverity

if TYPE_CHECKING:
    from protokit.schema.lint.model import FileLintContext


@lint_rule(
    rule_id="file/syntax-specified",
    severity=LintSeverity.ERROR,
    profiles=("recommended", "default"),
    element=ElementKind.FILE,
    message_template=(
        "File {file!r} does not declare ``syntax = \"proto3\";``; "
        "protokit treats proto2 (whether explicit or implicit) as "
        "a parity violation — declare proto3 explicitly or demote "
        "this rule via [tool.protokit.lint.severities] if proto2 "
        "is intentional"
    ),
    source_spec="buf:SYNTAX_SPECIFIED",
)
def check_syntax_specified(ctx: FileLintContext) -> None:
    """Fire when the file's resolved syntax is not ``proto3``.

    The descriptor pool does not preserve enough source-level
    information to distinguish "no syntax statement at all" from
    explicit ``syntax = "proto2";`` — the protobuf compiler emits
    ``fdp.syntax == ""`` for both cases (the field is only set for
    non-default syntax: ``"proto3"`` and ``"editions"``).

    Buf's SYNTAX_SPECIFIED rule fires only on the no-statement
    case (it parses .proto source directly). Protokit can only
    work from descriptor output, so the rule fires on both cases.
    This is stricter than buf and intentionally nudges users
    toward proto3; users with intentional proto2 codebases can
    demote the rule via ``[tool.protokit.lint.severities]``.

    Future editions (proto-editions, recorded as
    ``fdp.syntax == "editions"`` or similar) are out of scope for
    D6a — when editions support lands, this rule should accept
    editions as also-clean.
    """
    fdp = descriptor_pb2.FileDescriptorProto()
    ctx.file.CopyToProto(fdp)
    if fdp.syntax != "proto3":
        ctx.emit(
            violation_kind="file/syntax-specified",
            params={"file": ctx.file.name},
        )


# Module-level RULES tuple read by ``LintEngine.load_rule_pack``.
RULES: tuple[Callable[..., None], ...] = (
    check_syntax_specified,
)
