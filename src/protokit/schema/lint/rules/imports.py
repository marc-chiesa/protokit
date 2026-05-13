"""``imports`` rule pack — import-discipline rules for protokit-lint.

Buf BASIC parity rules covering the `import` statement family of a
`.proto` file. Three rules ship:

- ``imports/no-public`` (buf:IMPORT_NO_PUBLIC) — fires for every
  ``import public "...";`` declaration. Public imports re-export
  the imported file's symbols and create transitive coupling that
  is hard to reason about; buf BASIC discourages them in
  modern proto repos.
- ``imports/no-weak`` (buf:IMPORT_NO_WEAK) — fires for every
  ``import weak "...";`` declaration. Weak imports are a
  google-internal compat mechanism for breaking circular
  dependencies in legacy proto trees; buf BASIC discourages them
  in modern proto repos.
- ``imports/unused`` (buf:IMPORT_USED) — fires for every ordinary
  ``import "...";`` whose imported file's types are not referenced
  anywhere in the importing file's messages, services, methods,
  enum-value defaults, or field types. Public and weak imports
  are intentionally excluded from the unused check — they exist
  for re-export and compat reasons that do not require local
  reference.

Module shape mirrors :mod:`protokit.schema.lint.rules.naming` and
:mod:`protokit.schema.lint.rules.enum`: a top-level ``RULES`` tuple
of ``@lint_rule``-decorated callables, each carrying its
``LintRuleSpec`` on ``fn._lint_spec``.

**Descriptor introspection — CopyToProto round-trip.** The python
protobuf runtime's ``FileDescriptor`` does NOT expose
``public_dependency`` / ``weak_dependency`` index arrays directly;
those live only on the proto-message form ``FileDescriptorProto``.
The rules round-trip through ``ctx.file.CopyToProto(fdp)`` to read
them. ``fdp.dependency`` is the full list of imports in declaration
order; ``fdp.public_dependency`` and ``fdp.weak_dependency`` are
index lists into ``fdp.dependency``. The serialization is cheap
and free of version-skew risk — these arrays are populated by both
backends (protoc + protoxy) regardless of whether
``include_source_info`` was set.

References:
- buf BASIC rule catalog (parity targets named per-rule via
  ``source_spec="buf:<RULE_ID>"``).
- protokit-lint D6a plan, Unit 5:
  ``docs/plans/2026-05-12-001-feat-protokit-lint-d6a-rule-library-plan.md``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from google.protobuf import descriptor_pb2

from protokit.schema.lint.decorator import lint_rule
from protokit.schema.lint.model import ElementKind, LintSeverity

if TYPE_CHECKING:
    from google.protobuf import descriptor as proto_descriptor

    from protokit.schema.lint.model import FileLintContext


@lint_rule(
    rule_id="imports/no-public",
    severity=LintSeverity.ERROR,
    profiles=("recommended", "default"),
    element=ElementKind.FILE,
    message_template=(
        "File imports {imported!r} as ``public``; public imports "
        "create transitive re-export coupling and are discouraged"
    ),
    source_spec="buf:IMPORT_NO_PUBLIC",
)
def check_no_public_imports(ctx: FileLintContext) -> None:
    """Fire on every ``import public "...";`` declaration in the file.

    The runtime ``FileDescriptor`` does not expose
    ``public_dependency`` indices, so the rule serializes back to
    ``FileDescriptorProto`` via ``CopyToProto`` and reads the
    proto-form arrays. One finding is emitted per public import
    so the report enumerates every offender rather than collapsing
    them into a single ambiguous message.
    """
    fdp = descriptor_pb2.FileDescriptorProto()
    ctx.file.CopyToProto(fdp)
    for idx in fdp.public_dependency:
        ctx.emit(
            violation_kind="imports/no-public",
            params={"imported": fdp.dependency[idx]},
        )


@lint_rule(
    rule_id="imports/no-weak",
    severity=LintSeverity.ERROR,
    profiles=("recommended", "default"),
    element=ElementKind.FILE,
    message_template=(
        "File imports {imported!r} as ``weak``; weak imports are a "
        "legacy compat mechanism and are discouraged in modern proto"
    ),
    source_spec="buf:IMPORT_NO_WEAK",
)
def check_no_weak_imports(ctx: FileLintContext) -> None:
    """Fire on every ``import weak "...";`` declaration in the file."""
    fdp = descriptor_pb2.FileDescriptorProto()
    ctx.file.CopyToProto(fdp)
    for idx in fdp.weak_dependency:
        ctx.emit(
            violation_kind="imports/no-weak",
            params={"imported": fdp.dependency[idx]},
        )


@lint_rule(
    rule_id="imports/unused",
    severity=LintSeverity.ERROR,
    profiles=("recommended", "default"),
    element=ElementKind.FILE,
    message_template=(
        "File imports {imported!r} but does not reference any of its "
        "types — drop the import or mark it ``public``/``weak`` if "
        "the re-export is intentional"
    ),
    source_spec="buf:IMPORT_USED",
)
def check_unused_imports(ctx: FileLintContext) -> None:
    """Fire on every ordinary import whose types are not locally referenced.

    Walks the file's messages (including nested types), services,
    and methods, collecting the file names of every referenced
    message-type and enum-type descriptor. Compares the resulting
    "used file" set against ``fdp.dependency``. Public and weak
    imports are skipped — they exist for re-export and compat
    reasons that do not require local reference.

    The walk covers:

    - Field types on top-level + nested messages (message_type +
      enum_type slots). Map fields are covered transitively via
      the synthetic ``<Field>Entry`` nested message that the
      compiler generates for each map.
    - Method input + output types on every service.

    Not covered (out of scope for D6a — narrow protobuf surfaces
    where buf itself is similarly limited):

    - proto2 extensions of types in other files.
    - Custom options whose definitions live in other files.

    The rule mirrors buf's IMPORT_USED behavior: a public-imported
    file used only as a re-export is not flagged; a weak-imported
    file used only for compat is not flagged.
    """
    fdp = descriptor_pb2.FileDescriptorProto()
    ctx.file.CopyToProto(fdp)
    if not fdp.dependency:
        return

    used_files: set[str] = set()

    def _record(descriptor: proto_descriptor.DescriptorBase | None) -> None:
        if descriptor is None:
            return
        used_files.add(descriptor.file.name)

    def _walk_message(msg: proto_descriptor.Descriptor) -> None:
        for field in msg.fields:
            _record(field.message_type)
            _record(field.enum_type)
        for nested in msg.nested_types:
            _walk_message(nested)
        for nested_enum in msg.enum_types:
            # enums declared inside this message live in this file;
            # no cross-file usage to record here. Skipping keeps the
            # used_files set focused on referenced symbols.
            del nested_enum

    for msg in ctx.file.message_types_by_name.values():
        _walk_message(msg)

    for service in ctx.file.services_by_name.values():
        for method in service.methods:
            _record(method.input_type)
            _record(method.output_type)

    # Self-reference is never an "import" — drop it defensively.
    used_files.discard(ctx.file.name)

    public_idx = set(fdp.public_dependency)
    weak_idx = set(fdp.weak_dependency)
    for idx, imported_name in enumerate(fdp.dependency):
        if idx in public_idx or idx in weak_idx:
            # Public + weak imports have other rules (no-public,
            # no-weak); their "unused" status is a different concern
            # the user has signaled intent on by choosing those
            # import modes. Skip the unused-check on those entries
            # to mirror buf BASIC's IMPORT_USED semantics.
            continue
        if imported_name not in used_files:
            ctx.emit(
                violation_kind="imports/unused",
                params={"imported": imported_name},
            )


# Module-level RULES tuple read by ``LintEngine.load_rule_pack``.
RULES: tuple[Callable[..., None], ...] = (
    check_no_public_imports,
    check_no_weak_imports,
    check_unused_imports,
)
