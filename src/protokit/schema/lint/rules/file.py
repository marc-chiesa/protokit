"""``file`` rule pack — file-level structural rules.

Currently ships one rule:

- ``file/syntax-specified`` (buf:SYNTAX_SPECIFIED) — fires when
  the file's resolved syntax is not ``"proto3"`` or ``"editions"``.
  **Default severity: WARNING** (demoted from the original ERROR
  default). **Known buf-parity divergence**: buf's own
  SYNTAX_SPECIFIED rule fires only when the literal
  ``syntax = "...";`` declaration is missing from the .proto
  source. Protokit's rule operates on descriptor output, where
  the protobuf compiler emits ``fdp.syntax == ""`` for BOTH
  "no syntax statement at all" AND ``syntax = "proto2";`` files
  — the descriptor cannot distinguish the two cases. Protokit
  therefore fires on every proto2 file regardless of whether
  the syntax statement was explicit.

**WARNING demotion (pragmatic-not-dogmatic):** the rule's prior
ERROR behavior actively contradicted protokit's UX-over-parity
philosophy — firing ERROR on every proto2 file is opinionated
proto2-hostility in default profiles, which that philosophy
rejects. The rule still surfaces the signal ("we recommend
declaring syntax explicitly so future readers don't have to
guess proto2 from descriptor shape") but does NOT fail CI on
proto2 files by default. Proto3-only shops who relied on the
ERROR enforcement can re-promote via ``[tool.protokit.lint
.severities] "file/syntax-specified" = "error"``.

The CopyToProto round-trip pattern is used here because
``FileDescriptor.syntax`` is not exposed on the upb backend's
runtime descriptor (see
``docs/solutions/best-practices/copytoproto-round-trip-for-proto-form-only-descriptor-fields-2026-05-13.md``).
Reading ``fdp.syntax`` after ``ctx.file.CopyToProto(fdp)`` is the
documented, stable, backend-agnostic path.

Module shape mirrors the other rule packs.

References:
- buf BASIC rule catalog (parity targets named per-rule via
  ``source_spec="buf:<RULE_ID>"``).
- See the project's design notes for the original ERROR-default
  rationale and the subsequent WARNING demotion under the
  inverted UX philosophy.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from google.protobuf import descriptor_pb2

from protokit.schema.lint.decorator import lint_rule
from protokit.schema.lint.model import ElementKind, LintSeverity

if TYPE_CHECKING:
    from protokit.schema.lint.model import FileLintContext


#: Syntaxes the rule treats as "specified" and clean. Proto3 is
#: the primary D6a target; ``editions`` is included so files that
#: explicitly opt into proto-editions (recorded as
#: ``fdp.syntax == "editions"`` by the protobuf compiler) are
#: treated as also-clean, matching the rule docstring's stated
#: intent. Empty (``""``) covers both no-statement files and
#: explicit ``syntax = "proto2";``, and the rule fires on those —
#: see the documented buf-parity divergence below.
_CLEAN_SYNTAXES: frozenset[str] = frozenset({"proto3", "editions"})


@lint_rule(
    rule_id="file/syntax-specified",
    severity=LintSeverity.WARNING,
    profiles=("recommended", "default"),
    element=ElementKind.FILE,
    message_template=(
        "File {file!r} does not declare ``syntax = \"proto3\";`` "
        "(or ``edition = \"...\";``); protokit recommends "
        "declaring syntax explicitly so future readers don't "
        "have to guess proto2 from descriptor shape — "
        "re-promote to ERROR via [tool.protokit.lint.severities] "
        "\"file/syntax-specified\" = \"error\" if your project "
        "is proto3-only"
    ),
    source_spec="buf:SYNTAX_SPECIFIED",
)
def check_syntax_specified(ctx: FileLintContext) -> None:
    """Fire (at WARNING) when the file's resolved syntax is not
    proto3 or editions.

    The descriptor pool does not preserve enough source-level
    information to distinguish "no syntax statement at all" from
    explicit ``syntax = "proto2";`` — the protobuf compiler emits
    ``fdp.syntax == ""`` for both cases (the field is only set for
    non-default syntax: ``"proto3"`` and ``"editions"``).

    Buf's SYNTAX_SPECIFIED rule fires only on the no-statement
    case (it parses .proto source directly). Protokit can only
    work from descriptor output, so the rule fires on both
    no-syntax and explicit-proto2 cases.

    **Severity WARNING in default profiles**. The rule's spirit
    is "declare syntax explicitly so future readers don't have to
    guess" — surfacing the signal at WARNING is sufficient.
    Proto3-only shops who relied on the prior ERROR enforcement
    can re-promote via
    ``[tool.protokit.lint.severities] "file/syntax-specified" =
    "error"``.

    **Editions support**: files that explicitly opt into
    proto-editions (``fdp.syntax == "editions"``) are treated as
    clean — the rule's spirit is "did you opt into a non-default
    syntax", and editions IS an explicit opt-in. The
    ``_CLEAN_SYNTAXES`` frozenset documents the accepted values.
    """
    fdp = descriptor_pb2.FileDescriptorProto()
    ctx.file.CopyToProto(fdp)
    if fdp.syntax not in _CLEAN_SYNTAXES:
        ctx.emit(
            violation_kind="file/syntax-specified",
            params={"file": ctx.file.name},
        )


# Module-level RULES tuple read by ``LintEngine.load_rule_pack``.
RULES: tuple[Callable[..., None], ...] = (
    check_syntax_specified,
)
