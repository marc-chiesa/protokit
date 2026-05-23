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

The first two rules (``package/defined`` + ``package/directory-match``)
use ``ctx.file.name`` and ``ctx.file.package`` from the runtime
descriptor — no CopyToProto round-trip needed for these particular
fields. Cross-file behavior follows the established ``fd.name``
POSIX-separator convention (see
``docs/solutions/logic-errors/matcher-backend-path-resolution-skew-silently-empties-output-2026-05-02.md``);
``check_package_directory_match`` uses ``pathlib.PurePosixPath`` to
split the directory portion, matching the convention.

The two cross-file rules (R8 + R8b) consume the dual-view
accumulator landed in D6c U1 via
``FileLintContext.directory_packages`` (per-package view, R8) +
``FileLintContext.directory_packages_by_dir`` (per-directory
inverted index, R8b). Both iterate over a single shared pre-walk
pass; neither rule re-walks the descriptor pool. R8b uses
``posixpath.dirname`` (NOT ``PurePosixPath``) at the per-file call
site so its current-dir key format byte-matches the accumulator
keys built by ``LintEngine._build_directory_package_accumulator``
(also ``posixpath``-based) — the two path APIs coexist in this
module because each rule's lookup path requires the matching key
format, not because the file mixes conventions casually.

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

from protokit.schema.lint._cli_utils import _safe_for_stderr
from protokit.schema.lint.decorator import lint_rule
from protokit.schema.lint.model import ElementKind, FileLocation, LintSeverity

if TYPE_CHECKING:
    from protokit.schema.lint.model import FileLintContext

# 500-char cap applied to every string param emitted by R8/R8b (and
# to the composed payload string for R8b). Mirrors R7's
# ``_check_package_option`` discipline in package_same.py — adversarial
# values containing U+2028/U+2029 line terminators (which buf v1.69.0
# may emit verbatim into NDJSON, injecting record boundaries) flow
# through ``_safe_for_stderr`` to collapse the control characters, and
# the cap bounds the DoS surface when N is extreme (e.g., a package
# split across 500 directories). The cap is applied to each param
# independently after composition; the composed payload also receives
# its own cap so the rendered message never exceeds 500 chars + the
# template wrapper.
_PARAM_CAP = 500


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
    template at all N values (per the D6c plan's KTD-4 (e)
    empirical verification — see ``docs/plans/2026-05-18-003-
    feat-d6c-r8-r8b-cross-file-package-rules-plan.md``). Example
    output: ``Multiple directories "d1,d2,d3" contain files with
    package "acme.x".``.

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
    fire semantics. Empirically verified per the D6c plan's KTD-9
    co-fire fixture.
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
    # Sanitize + cap per R7's discipline (package_same.py:_check_
    # package_option). U+2028/U+2029 in any single directory name
    # would otherwise inject NDJSON record boundaries; the per-param
    # cap bounds the DoS surface on extreme split counts.
    ctx.emit(
        violation_kind="package/same-directory",
        params={
            "file": _safe_for_stderr(ctx.file.name)[:_PARAM_CAP],
            "package": _safe_for_stderr(pkg)[:_PARAM_CAP],
            "directories": _safe_for_stderr(
                ",".join(distinct_dirs),
            )[:_PARAM_CAP],
        },
    )


#: R8b's three empirically-locked message templates, keyed by
#: ``violation_kind``. Buf v1.69.0 uses three distinct sentence shapes
#: depending on the directory's package mix:
#:
#: - **Standard** (2+ declared, no packageless):
#:   ``Multiple packages "X,Y[,Z]" detected within directory "D".``
#: - **Empty-mixed-single** (exactly 1 declared + ≥1 packageless):
#:   ``Package "X" and file with no package detected within directory "D".``
#: - **Empty-mixed-multi** (2+ declared + ≥1 packageless):
#:   ``Multiple packages "X,Y[,Z]" and file with no package detected within
#:   directory "D".``
#:
#: The third arm was added at U3 ce:work (2026-05-19) after the parity
#: gate's first run surfaced a real divergence from buf v1.69.0 on the
#: multi-declared+packageless ``no-package-mixed`` fixture — the U2 plan's
#: KTD-4 (b) claim that buf "produces exactly one declared-package value
#: in this template even if multiple declared packages exist" was based
#: on a Phase 0 fixture that had only 1 declared + 2 packageless. Buf
#: actually renders ALL declared packages in this case with the
#: ``Multiple packages "..."`` prefix instead of ``Package "..."``.
#: See [[empirical-parity-gate-surfaces-latent-helper-bug-at-implementation-time-2026-05-18]]
#: Case 4 for the latent-helper-bug pattern.
#:
#: Dict-shaped ``message_template`` keyed by ``violation_kind`` so each
#: arm is a separately introspectable per-kind template (SARIF rules
#: catalog reads the per-kind shortDescription rather than the literal
#: ``"{payload}"`` identity-template the rule shipped with at U2's
#: initial drop).
_R8B_STANDARD_KIND = "package/directory-same-package"
_R8B_EMPTY_MIXED_SINGLE_KIND = (
    "package/directory-same-package/empty-mixed-single"
)
_R8B_EMPTY_MIXED_MULTI_KIND = (
    "package/directory-same-package/empty-mixed-multi"
)
_R8B_MESSAGE_TEMPLATES: dict[str, str] = {
    _R8B_STANDARD_KIND: (
        'Multiple packages "{packages}" '
        'detected within directory "{directory}".'
    ),
    _R8B_EMPTY_MIXED_SINGLE_KIND: (
        'Package "{package}" and file with no package '
        'detected within directory "{directory}".'
    ),
    _R8B_EMPTY_MIXED_MULTI_KIND: (
        'Multiple packages "{packages}" and file with no package '
        'detected within directory "{directory}".'
    ),
}
_R8B_SEVERITIES: dict[str, LintSeverity] = {
    _R8B_STANDARD_KIND: LintSeverity.ERROR,
    _R8B_EMPTY_MIXED_SINGLE_KIND: LintSeverity.ERROR,
    _R8B_EMPTY_MIXED_MULTI_KIND: LintSeverity.ERROR,
}


@lint_rule(
    rule_id="package/directory-same-package",
    severity=_R8B_SEVERITIES,
    profiles=("recommended", "default"),
    element=ElementKind.FILE,
    message_template=_R8B_MESSAGE_TEMPLATES,
    source_spec="buf:DIRECTORY_SAME_PACKAGE",
)
def check_directory_same_package(ctx: FileLintContext) -> None:
    """Fire when a single directory contains files declaring multiple packages.

    Consumes ``ctx.directory_packages_by_dir`` (the per-directory
    inverted-index view built by D6c U1). Lookup is by the current
    file's directory — if more than one package key occurs in the
    inner ``{pkg: frozenset[fname]}`` mapping, emit a per-file
    finding.

    **Three message-template arms**, all empirically locked against
    buf v1.69.0:

    - **Standard** (2+ declared packages, no packageless):
      ``Multiple packages "X,Y[,Z]" detected within directory "Z".``
      Package list is comma-no-space, alphabetic-sorted (per the D6c
      plan's KTD-4 (e) empirical verification — see
      ``docs/plans/2026-05-18-003-feat-d6c-r8-r8b-cross-file-package-rules-plan.md``).
    - **Empty-mixed-single** (exactly 1 declared + ≥1 packageless):
      ``Package "X" and file with no package detected within directory "Y".``
      Buf renders the single declared-package value verbatim. Phase 0
      verified this arm.
    - **Empty-mixed-multi** (2+ declared + ≥1 packageless): ``Multiple
      packages "X,Y[,Z]" and file with no package detected within
      directory "Y".`` Buf renders ALL declared packages in
      comma-separated alphabetic order — distinct from the
      single-declared arm. **Discovered at U3 ce:work (2026-05-19)**:
      U2's R8b implementation only handled the single-declared case
      because the plan's KTD-4 (b) verification used a 1-declared + 2-
      packageless Phase 0 fixture. U3's ``no-package-mixed`` parity
      fixture (2-declared + 1-packageless) surfaced the missing arm per
      [[empirical-parity-gate-surfaces-latent-helper-bug-at-implementation-time-2026-05-18]].

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
    root file in the directory). Empirically verified per the D6c
    plan's KTD-9 co-fire fixture.
    """
    if ctx.directory_packages_by_dir is None:
        return
    # ``posixpath.dirname`` (NOT ``PurePosixPath.parent``) so the
    # current-dir key BYTE-matches the accumulator's key format —
    # ``_build_directory_package_accumulator`` in ``engine.py`` also
    # uses ``posixpath.dirname(fname) or "."``. PurePosixPath would
    # canonicalize ``"a//b.proto"`` differently and miss the bucket.
    current_dir = posixpath.dirname(ctx.file.name) or "."
    pkg_map = ctx.directory_packages_by_dir.get(current_dir)
    if pkg_map is None or len(pkg_map) <= 1:
        return
    declared_pkgs = sorted(p for p in pkg_map if p)
    packageless_present = "" in pkg_map
    # Sanitize the directory key BEFORE composing params so the
    # template-rendered string also benefits from the U+2028/U+2029
    # collapse + 500-char cap per R7's discipline.
    safe_dir = _safe_for_stderr(current_dir)[:_PARAM_CAP]
    safe_file = _safe_for_stderr(ctx.file.name)[:_PARAM_CAP]
    # Three-arm dispatch (empty-mixed-single, empty-mixed-multi,
    # standard) keyed by ``violation_kind`` so the formatter picks the
    # right per-arm template from the dict-shaped ``message_template``.
    # Each arm's ``params`` keys mirror the placeholders in its
    # template — ``package`` (singular) for empty-mixed-single,
    # ``packages`` (plural CSV) for both empty-mixed-multi and standard.
    if packageless_present and len(declared_pkgs) == 1:
        # Empty-mixed-single arm: exactly one declared package
        # co-occurs with packageless files. Verified at Phase 0
        # (1-declared + 2-packageless fixture).
        declared = _safe_for_stderr(declared_pkgs[0])[:_PARAM_CAP]
        ctx.emit(
            violation_kind=_R8B_EMPTY_MIXED_SINGLE_KIND,
            params={
                "file": safe_file,
                "directory": safe_dir,
                "package": declared,
                "packageless_present": True,
            },
        )
    elif packageless_present and len(declared_pkgs) >= 2:
        # Empty-mixed-multi arm: 2+ declared packages + packageless
        # files co-occur. Buf empirically renders ALL declared packages
        # in this case (verified at U3's ``no-package-mixed`` fixture,
        # 2026-05-19). U2 shipped this arm as a single-declared
        # passthrough; U3's parity gate surfaced the divergence.
        pkg_list = _safe_for_stderr(",".join(declared_pkgs))[:_PARAM_CAP]
        ctx.emit(
            violation_kind=_R8B_EMPTY_MIXED_MULTI_KIND,
            params={
                "file": safe_file,
                "directory": safe_dir,
                "packages": pkg_list,
                "packageless_present": True,
            },
        )
    else:
        # Standard arm: 2+ declared packages, NO packageless files.
        pkg_list = _safe_for_stderr(",".join(declared_pkgs))[:_PARAM_CAP]
        ctx.emit(
            violation_kind=_R8B_STANDARD_KIND,
            params={
                "file": safe_file,
                "directory": safe_dir,
                "packages": pkg_list,
                "packageless_present": False,
            },
        )


@lint_rule(
    rule_id="package/no-import-cycle",
    severity=LintSeverity.ERROR,
    profiles=("recommended", "default"),
    element=ElementKind.FILE,
    message_template=(
        "Package import cycle: {cycle_path_rendered}"
    ),
    source_spec="buf:PACKAGE_NO_IMPORT_CYCLE",
)
def check_package_no_import_cycle(ctx: FileLintContext) -> None:
    """Fire on package-level import cycles (D6e U3 / 26th buf BASIC rule).

    Consumes the per-file cycle-closing-import map built by
    :meth:`LintEngine._build_import_graph_accumulator` (Step 3.5c
    pre-walk). Each entry in ``ctx.import_cycles[ctx.file.name]``
    is a :class:`CycleEdge` describing one ``import`` statement
    whose target package is in the same package-level SCC as the
    source file's package. Emits ONE finding per cycle-closing
    edge, pointing at the import statement's line/column when
    ``include_source_info=True`` is in effect (the lint CLI's
    ``--proto`` mode default per D6b U3a; descriptor-set input
    without source_info emits at whole-file FileLocation).

    **Phase 0 binding** (2026-05-22, see plan PD-6 + PD-14):
    file-level import cycles are caught at the COMPILE phase
    (both buf v1.69.0 and protoxy reject them at parse layer).
    This rule's actual operational ground is the rarer PACKAGE-
    LEVEL cycle case where individual file imports are acyclic
    but the package graph cycles. Example: ``pkg_a/a1.proto``
    imports ``pkg_b/b1.proto`` AND ``pkg_b/b2.proto`` imports
    ``pkg_a/a2.proto`` — file graph acyclic, package graph
    cyclic.

    **Emission shape** matches buf v1.69.0 per Phase 0:
    per-import-edge (one finding per cycle-closing ``import``
    statement). Sibling "leaf" files in cyclic packages that
    don't have cycle-closing imports themselves do NOT emit
    findings (this addresses the UX over-emission concern raised
    at ce:review session 2026-05-22).

    **Message format** matches buf v1.69.0:
    ``"Package import cycle: <self_pkg> -> <pkg_2> -> ... ->
    <self_pkg>"`` (cycle path rotated so self's package leads).
    """
    if ctx.import_cycles is None:
        return  # accumulator skipped (empty root_files)
    edges = ctx.import_cycles.get(ctx.file.name)
    if not edges:
        return
    safe_file = _safe_for_stderr(ctx.file.name)[:_PARAM_CAP]
    for edge in edges:
        # Render the cycle path for the message template.
        # ``cycle_path`` is already rotated so the source
        # package leads + closes the loop (e.g., ``("acme.a",
        # "acme.b", "acme.a")``).
        cycle_rendered = " -> ".join(edge.cycle_path)
        safe_imported = _safe_for_stderr(edge.imported_file)[:_PARAM_CAP]
        safe_target_pkg = _safe_for_stderr(edge.target_package)[:_PARAM_CAP]
        safe_cycle_rendered = _safe_for_stderr(cycle_rendered)[:_PARAM_CAP]
        ctx.emit(
            violation_kind="package/no-import-cycle",
            params={
                "file": safe_file,
                "imported_file": safe_imported,
                "target_package": safe_target_pkg,
                "cycle_path_rendered": safe_cycle_rendered,
            },
            location=FileLocation(
                file=ctx.file.name,
                line=edge.line,
                column=edge.column,
            ),
        )


# Module-level RULES tuple read by ``LintEngine.load_rule_pack``.
#
# **R8b before R8 ordering is LOAD-BEARING for buf v1.69.0 parity.** The
# engine dispatches rules in pack-registration order within each
# ``ElementKind`` bucket (``LintEngine._loaded_specs`` is an
# insertion-ordered dict consumed by ``_dispatch_file`` without an
# intermediate sort). Buf v1.69.0 emits ``DIRECTORY_SAME_PACKAGE`` (R8b)
# BEFORE ``PACKAGE_SAME_DIRECTORY`` (R8) when both fire on the same file
# — alphabetical by buf's rule_id. To match buf byte-for-byte on co-fire
# scenarios, R8b must appear before R8 in this tuple. The cofire-
# ordering presence-ratchet in
# :class:`tests.schema.lint.rules.test_package_same_directory.TestCofireScenario`
# pins this contract. A future engine refactor that adds per-file
# alphabetic sorting would make this ordering incidental rather than
# load-bearing; until that refactor lands, do not reorder this tuple.
#
# **D6e U3 placement**: ``check_package_no_import_cycle`` slots
# alphabetically between PACKAGE_DIRECTORY_MATCH and PACKAGE_SAME_DIRECTORY
# (alphabetical co-fire ordering by buf rule_id places
# PACKAGE_NO_IMPORT_CYCLE between them). Insertion order in this tuple
# matches that alphabetical position when co-fire occurs — though Phase 0
# did not surface a multi-rule co-fire fixture so the empirical pinning
# happens at U3's parity gate, not here.
RULES: tuple[Callable[..., None], ...] = (
    check_package_defined,
    check_package_directory_match,
    check_directory_same_package,
    check_package_no_import_cycle,
    check_package_same_directory,
)
