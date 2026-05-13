"""``package`` rule pack — package-declaration structural rules.

Buf BASIC parity rules covering the file's ``package`` statement:

- ``package/defined`` (buf:PACKAGE_DEFINED) — fires when the file
  has no ``package`` declaration. Files without a package land in
  the protobuf default namespace, which is a footgun for any
  multi-file project: name collisions become silent and refactors
  cascade unpredictably.
- ``package/directory-match`` (buf:PACKAGE_DIRECTORY_MATCH) —
  fires when the file's package does not match the file's
  directory path. E.g., a file at ``acme/api/v1/users.proto`` is
  expected to declare ``package acme.api.v1;`` — the package
  segments and the directory path segments must align.

Module shape mirrors :mod:`protokit.schema.lint.rules.naming` /
:mod:`protokit.schema.lint.rules.enum` / :mod:`protokit.schema.lint.rules.imports`:
a top-level ``RULES`` tuple of ``@lint_rule``-decorated callables.

Both rules use ``ctx.file.name`` and ``ctx.file.package`` from the
runtime descriptor — no CopyToProto round-trip needed for these
particular fields (the runtime API exposes both). Cross-file
behavior follows the established ``fd.name`` POSIX-separator
convention (see
``docs/solutions/logic-errors/matcher-backend-path-resolution-skew-silently-empties-output-2026-05-02.md``);
the rules use ``pathlib.PurePosixPath`` to split the directory
portion, matching the convention.

The ``package/same-directory`` rule (buf:PACKAGE_SAME_DIRECTORY)
is deferred to D6b alongside the rest of the cross-language
``PACKAGE_SAME_*`` family — it is a cross-file rule that requires
comparing multiple files' package declarations, and the current
engine dispatches FILE-level rules one file at a time with no
cross-call state.

References:
- buf BASIC rule catalog (parity targets named per-rule via
  ``source_spec="buf:<RULE_ID>"``).
- protokit-lint D6a plan, Unit 6:
  ``docs/plans/2026-05-12-001-feat-protokit-lint-d6a-rule-library-plan.md``.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from protokit.schema.lint.decorator import lint_rule
from protokit.schema.lint.model import ElementKind, LintSeverity

if TYPE_CHECKING:
    from protokit.schema.lint.model import FileLintContext


# Each directory segment that maps to a package segment must be a
# valid protobuf identifier. Used by check_package_directory_match
# to skip files whose ``fd.name`` parent contains parts that cannot
# form a valid package (root ``/`` anchor on absolute paths, ``..``
# on un-normalized relative paths, hyphens, leading digits, etc.).
# Protobuf-descriptor convention forbids most of these, but the
# guard hardens against future edge cases (a synthesized
# descriptor, a manual fixture, a backend that doesn't normalize).
_PROTO_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@lint_rule(
    rule_id="package/defined",
    severity=LintSeverity.ERROR,
    profiles=("recommended", "default"),
    element=ElementKind.FILE,
    message_template=(
        "File {file!r} has no ``package`` declaration; "
        "files without a package land in the protobuf default "
        "namespace and risk silent name collisions"
    ),
    source_spec="buf:PACKAGE_DEFINED",
)
def check_package_defined(ctx: FileLintContext) -> None:
    """Fire on files without a ``package`` declaration.

    A missing ``package`` statement leaves the file's top-level
    types in the protobuf default namespace, which is shared
    across every other package-less file in the same descriptor
    pool. Buf BASIC treats this as a hard error; protokit mirrors
    that posture at severity ERROR in the recommended/default
    profiles.
    """
    if not ctx.file.package:
        ctx.emit(
            violation_kind="package/defined",
            params={"file": ctx.file.name},
        )


@lint_rule(
    rule_id="package/directory-match",
    severity=LintSeverity.ERROR,
    profiles=("recommended", "default"),
    element=ElementKind.FILE,
    message_template=(
        "File {file!r} declares package {package!r}, but its "
        "directory path implies package {expected!r}; the canonical "
        "fix is to move the file into a directory whose snake_case "
        "segments match the declared package — adopting "
        "{expected!r} as the package may trigger "
        "``naming/snake-case-packages`` if any directory segment "
        "is not snake_case"
    ),
    source_spec="buf:PACKAGE_DIRECTORY_MATCH",
)
def check_package_directory_match(ctx: FileLintContext) -> None:
    """Fire when the file's package doesn't match its directory path.

    Splits ``ctx.file.name`` into directory + basename via
    ``PurePosixPath`` (the descriptor pool stores POSIX-separated
    file names by protobuf convention — see
    ``matcher-backend-path-resolution-skew-silently-empties-output``
    for the convention's origin). Joins the directory parts with
    ``.`` and compares the result to ``ctx.file.package`` as a
    string. Mismatches fire one finding per file.

    **Skipped cases** (no fire):

    - Files with no ``package`` declaration are skipped — that is
      the concern of ``package/defined`` and emitting both would
      double-count a single underlying violation.
    - Files at the top level (no directory portion) are skipped:
      there is no directory to match against, and protobuf does
      not require any particular package for top-level files.
      Buf has the same behavior; protokit mirrors.
    - Files whose directory parts cannot form a valid protobuf
      package are skipped — examples include the leading-``/``
      anchor on absolute paths (``/acme/v1/foo.proto`` →
      ``('/', 'acme', 'v1')``), un-normalized ``..`` segments
      (``acme/../v1/foo.proto`` → ``('acme', '..', 'v1')``), and
      hyphenated or leading-digit segments that the protobuf
      grammar forbids in package names. In those cases, no
      meaningful "expected" package can be derived from the
      directory; emitting a finding with a nonsense expected
      value would mislead users. Protobuf-descriptor convention
      forbids most of these inputs, but the guard hardens against
      synthesized descriptors and manual fixtures.

    **Cross-rule constraint**: per the
    ``lint-rule-message-templates-must-not-recommend-actions-that-trigger-siblings``
    learning, the ``message_template`` deliberately steers users
    toward *moving the file* to a snake_case directory rather than
    toward adopting ``{expected}`` as the package. If the directory
    has non-snake_case segments (``Acme/v1/foo.proto`` →
    ``Acme.v1``), the latter remediation would immediately trigger
    ``naming/snake-case-packages`` in the same recommended profile.
    The message names both fix paths so users hitting the
    cross-rule trap understand the routing.

    The directory anchor is the directory containing the file
    relative to the descriptor pool's record (``fd.name``). For
    a file recorded as ``acme/api/v1/users.proto``, the directory
    parts are ``("acme", "api", "v1")`` and the expected package
    is ``"acme.api.v1"``.
    """
    if not ctx.file.package:
        return  # package/defined's territory
    file_path = PurePosixPath(ctx.file.name)
    dir_parts = file_path.parent.parts
    if not dir_parts:
        return  # top-level file; no directory to match
    if not all(_PROTO_IDENTIFIER_RE.match(part) for part in dir_parts):
        # One or more directory parts cannot form a valid protobuf
        # package segment. Common causes: leading '/' anchor on
        # absolute paths, '..' from un-normalized relative paths,
        # hyphens, leading digits. Emitting an "expected" package
        # in these cases would be nonsense ("/.acme.v1",
        # "acme....v1"); skip the rule and let the user fix the
        # path representation upstream.
        return
    expected_package = ".".join(dir_parts)
    if ctx.file.package != expected_package:
        ctx.emit(
            violation_kind="package/directory-match",
            params={
                "file": ctx.file.name,
                "package": ctx.file.package,
                "expected": expected_package,
            },
        )


# Module-level RULES tuple read by ``LintEngine.load_rule_pack``.
RULES: tuple[Callable[..., None], ...] = (
    check_package_defined,
    check_package_directory_match,
)
