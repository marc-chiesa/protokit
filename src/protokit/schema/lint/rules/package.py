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
- ``package/same-directory`` (buf:PACKAGE_SAME_DIRECTORY) — D6c U2
  cross-file rule. Fires when a single package's files live in
  more than one directory.
- ``package/directory-same-package`` (buf:DIRECTORY_SAME_PACKAGE)
  — D6c U2 cross-file rule. Fires when a single directory contains
  files declaring more than one package (including the special
  empty-mixed arm when declared + packageless files co-occur).

Module shape mirrors :mod:`protokit.schema.lint.rules.naming` /
:mod:`protokit.schema.lint.rules.enum` / :mod:`protokit.schema.lint.rules.imports`:
a top-level ``RULES`` tuple of ``@lint_rule``-decorated callables.

The first two rules use ``ctx.file.name`` and ``ctx.file.package``
from the runtime descriptor — no CopyToProto round-trip needed
for these particular fields. Cross-file behavior follows the
established ``fd.name`` POSIX-separator convention (see
``docs/solutions/logic-errors/matcher-backend-path-resolution-skew-silently-empties-output-2026-05-02.md``);
the rules use ``pathlib.PurePosixPath`` to split the directory
portion, matching the convention.

The two cross-file rules (R8 + R8b) consume the dual-view
accumulator landed in D6c U1 via
``FileLintContext.directory_packages`` (per-package view, R8) +
``FileLintContext.directory_packages_by_dir`` (per-directory
inverted index, R8b). Both iterate over a single shared pre-walk
pass; neither rule re-walks the descriptor pool.

References:
- buf BASIC rule catalog (parity targets named per-rule via
  ``source_spec="buf:<RULE_ID>"``).
- protokit-lint D6a plan, Unit 6 (R8 + R8b precursors):
  ``docs/plans/2026-05-12-001-feat-protokit-lint-d6a-rule-library-plan.md``.
- protokit-lint D6c plan (R8 + R8b cross-file rule callables):
  ``docs/plans/2026-05-18-003-feat-d6c-r8-r8b-cross-file-package-rules-plan.md``.
"""

from __future__ import annotations

import posixpath
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


@lint_rule(
    rule_id="package/same-directory",
    severity=LintSeverity.ERROR,
    profiles=("recommended", "default"),
    element=ElementKind.FILE,
    message_template=(
        'Multiple directories "{directories}" contain '
        'files with package "{package}".'
    ),
    source_spec="buf:PACKAGE_SAME_DIRECTORY",
)
def check_package_same_directory(ctx: FileLintContext) -> None:
    """Fire when a single package's files span more than one directory.

    Consumes ``ctx.directory_packages`` (the per-package view built
    by ``LintEngine._build_directory_package_accumulator`` in D6c U1).
    Lookup is by ``ctx.file.package`` — if the inner ``{fname: dirname}``
    mapping contains more than one distinct ``dirname``, emit a per-file
    finding listing every directory.

    Directory list rendering is empirically locked against buf
    v1.69.0: comma-no-space, alphabetic-sorted, single message
    template at all N values (verified at
    ``/tmp/d6c_phase0/n3_dirs/``). Example output:
    ``Multiple directories "d1,d2,d3" contain files with package
    "acme.x".``.

    **Silent on**:

    - ``ctx.directory_packages is None`` — test-helper path; the
      engine pre-walk did not run (e.g., FileLintContext constructed
      directly via a unit-test helper bypassing
      :class:`LintEngine.run`).
    - ``ctx.file.package == ""`` — packageless files are R8b's
      concern (the empty-mixed template). R8 only flags conflicts
      where a single declared package straddles multiple
      directories; packageless files contribute no signal here.
    - ``per_pkg is None`` — defensive; the file's package is not in
      the accumulator (unreachable for any root file in the pool).
    - ``len(distinct_dirs) <= 1`` — single-directory package; the
      common happy path.

    Engine's per-file walk fires this rule once per root file, so a
    3-file package with a 2-directory split produces 3 findings
    (one per root file in the package) — buf v1.69.0 all-disagreers-
    fire semantics. Empirically verified at
    ``/tmp/d6c_phase0/cofire/``.
    """
    if ctx.directory_packages is None:
        return
    pkg = ctx.file.package
    if not pkg:
        return  # R8b's territory; R8 has no signal on packageless files
    per_pkg = ctx.directory_packages.get(pkg)
    if per_pkg is None:
        return
    distinct_dirs = sorted(set(per_pkg.values()))
    if len(distinct_dirs) <= 1:
        return
    ctx.emit(
        violation_kind="package/same-directory",
        params={
            "file": ctx.file.name,
            "package": pkg,
            "directories": ",".join(distinct_dirs),
        },
    )


@lint_rule(
    rule_id="package/directory-same-package",
    severity=LintSeverity.ERROR,
    profiles=("recommended", "default"),
    element=ElementKind.FILE,
    # Single composed payload — R8b has TWO distinct message-template
    # arms (standard vs empty-mixed) per buf v1.69.0 empirical lock.
    # Each arm composes the entire message text inline; the template
    # is the identity placeholder so str.format renders verbatim.
    # Semantic introspection fields (``directory``, ``package`` /
    # ``packages``, ``packageless_present``) are also present in
    # ``params`` for structured output (lint_json / lint_sarif).
    message_template="{payload}",
    source_spec="buf:DIRECTORY_SAME_PACKAGE",
)
def check_directory_same_package(ctx: FileLintContext) -> None:
    """Fire when a single directory contains files declaring multiple packages.

    Consumes ``ctx.directory_packages_by_dir`` (the per-directory
    inverted-index view built by D6c U1). Lookup is by the current
    file's directory — if more than one package key occurs in the
    inner ``{pkg: frozenset[fname]}`` mapping, emit a per-file
    finding.

    **Two message-template arms**, both empirically locked against
    buf v1.69.0:

    - **Standard** (all packages in the directory are declared):
      ``Multiple packages "X,Y[,Z]" detected within directory "Z".``
      Package list is comma-no-space, alphabetic-sorted (verified at
      ``/tmp/d6c_phase0/n3_pkgs/``).
    - **Empty-mixed** (directory contains at least one declared
      package AND at least one packageless file): ``Package "X" and
      file with no package detected within directory "Y".`` Buf
      empirically renders exactly one declared-package value in this
      arm even if multiple declared packages co-occur with the
      packageless file (verified at ``/tmp/d6c_phase0/empty_pkg/``);
      protokit picks the alphabetically-first declared package for
      determinism.

    Directory rendering: proto-root files canonicalize to ``"."``
    via ``posixpath.dirname(name) or "."`` (KTD-4 (c)). Buf renders
    proto-root as ``"directory \\".\\""``; protokit's canonicalization
    matches byte-for-byte.

    **Silent on**:

    - ``ctx.directory_packages_by_dir is None`` — test-helper path.
    - ``pkg_map is None`` — defensive; the file's directory is not
      in the accumulator (unreachable for any root file).
    - ``len(pkg_map) <= 1`` — single-package directory; the common
      happy path. Note: a directory of ALL-packageless files has
      ``pkg_map = {"": {fnames}}`` (length 1) and stays silent.

    Engine's per-file walk fires this rule once per root file, so a
    2-package directory with 3 files produces 3 findings (one per
    root file in the directory). Empirically verified at
    ``/tmp/d6c_phase0/cofire/``.
    """
    if ctx.directory_packages_by_dir is None:
        return
    current_dir = posixpath.dirname(ctx.file.name) or "."
    pkg_map = ctx.directory_packages_by_dir.get(current_dir)
    if pkg_map is None or len(pkg_map) <= 1:
        return
    declared_pkgs = sorted(p for p in pkg_map if p)
    packageless_present = "" in pkg_map
    if packageless_present and declared_pkgs:
        # Empty-mixed arm: declared + packageless files co-occur.
        # Buf renders a single declared-package value in this arm;
        # protokit picks alphabetically-first for determinism.
        declared = declared_pkgs[0]
        payload = (
            f'Package "{declared}" and file with no package '
            f'detected within directory "{current_dir}".'
        )
        params = {
            "file": ctx.file.name,
            "directory": current_dir,
            "package": declared,
            "packageless_present": True,
            "payload": payload,
        }
    else:
        # Standard arm: 2+ declared packages, no packageless files.
        pkg_list = ",".join(declared_pkgs)
        payload = (
            f'Multiple packages "{pkg_list}" '
            f'detected within directory "{current_dir}".'
        )
        params = {
            "file": ctx.file.name,
            "directory": current_dir,
            "packages": pkg_list,
            "packageless_present": False,
            "payload": payload,
        }
    ctx.emit(
        violation_kind="package/directory-same-package",
        params=params,
    )


# Module-level RULES tuple read by ``LintEngine.load_rule_pack``.
RULES: tuple[Callable[..., None], ...] = (
    check_package_defined,
    check_package_directory_match,
    check_package_same_directory,
    check_directory_same_package,
)
