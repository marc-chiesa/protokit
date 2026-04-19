"""Click CLI group for ``protokit compat``.

Subcommands:

- ``check`` — compatibility check between two descriptor sets,
  two ``.proto`` files, or two git refs (via ``--since`` /
  ``--against-base``).
- ``history`` — walk a git range and emit per-commit
  compatibility findings.
- ``bisect`` — find the earliest commit in a range that broke
  compatibility for a given type.
- ``ci`` — thin wrapper around ``check --against-base`` with
  CI-friendly defaults.

Exit codes (uniform across subcommands):
    0 — compatible (no findings survived the profile filter)
    1 — incompatible (at least one finding survived)
    2 — error (bad flags, missing type, protoc/git failure,
        rule-pack load failure, or any plugin-emitted Warning)
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from typing import Any

import click
from google.protobuf import descriptor_pool

from protokit._cli_utils import (
    compile_proto,
    error_exit,
    load_descriptor_pool,
)
from protokit.schema.checker import SchemaChecker
from protokit.schema.git import (
    GitRefNotFoundError,
    ProtoImportError,
    ShallowRepoError,
    commits_affecting_dep_tree,
    commits_in_range,
    extract_pool_from_ref,
    merge_base,
    resolve_default_base,
    verify_ref,
)
from protokit.schema.model import (
    CompatibilityLevel,
    CompatibilityReport,
    Finding,
    Severity,
)


# ---------------------------------------------------------------------------
# Level parsing
# ---------------------------------------------------------------------------

_LEVEL_CHOICES = ("wire", "consumer-safe", "producer-safe", "strict")
_LEVEL_LOOKUP = {
    "wire": CompatibilityLevel.WIRE,
    "consumer-safe": CompatibilityLevel.CONSUMER_SAFE,
    "producer-safe": CompatibilityLevel.PRODUCER_SAFE,
    "strict": CompatibilityLevel.STRICT,
}


def _resolve_level(level_flag: str) -> CompatibilityLevel:
    """Translate a CLI ``--level`` string into a ``CompatibilityLevel``.

    Args:
        level_flag: One of ``"wire"``, ``"consumer-safe"``,
            ``"producer-safe"``, or ``"strict"``.

    Returns:
        The matching ``CompatibilityLevel`` enum member.

    Raises:
        SystemExit: Via ``error_exit`` if the flag value is not a
            recognised level (should be prevented by Click's
            ``click.Choice``, but belt-and-suspenders).
    """
    try:
        return _LEVEL_LOOKUP[level_flag]
    except KeyError:
        error_exit(f"unknown --level '{level_flag}'")


# ---------------------------------------------------------------------------
# Descriptor-set loading with error-to-exit translation
# ---------------------------------------------------------------------------


def _safe_load_pool(
    path: Path,
    *,
    label: str,
) -> descriptor_pool.DescriptorPool:
    """Wrap :func:`load_descriptor_pool` and translate failures to exit code 2.

    Args:
        path: Descriptor-set path, already validated as readable by
            Click's ``click.Path(exists=True)``.
        label: Argument name (``"OLD_INPUT"`` or ``"NEW_INPUT"``)
            used in the error message for disambiguation.

    Returns:
        A fresh ``DescriptorPool`` loaded from ``path``.

    Raises:
        SystemExit: Via :func:`error_exit` if the file can't be read
            or can't be parsed as a ``FileDescriptorSet``.
    """
    try:
        return load_descriptor_pool(path)
    except (OSError, PermissionError) as exc:
        error_exit(f"cannot read {label} ({path}): {exc}")
    except Exception as exc:  # covers protobuf DecodeError and pool Add failures
        error_exit(f"failed to load {label} ({path}): {exc}")


# ---------------------------------------------------------------------------
# Rule-pack loading
# ---------------------------------------------------------------------------


def _load_rule_packs(checker: SchemaChecker, module_names: tuple[str, ...]) -> None:
    """Import each module by name and load its ``RULES`` into the checker.

    Args:
        checker: The ``SchemaChecker`` to register plugins on.
        module_names: Fully-qualified dotted module names to import
            via ``importlib.import_module``. Each module must expose
            a ``RULES`` attribute (see
            :func:`protokit.schema.plugins.iter_rule_pack`).

    Raises:
        SystemExit: Via ``error_exit`` on import failure, missing
            ``RULES`` attribute, or malformed ``RULES`` entries.
    """
    for name in module_names:
        try:
            module = importlib.import_module(name)
        except Exception as exc:
            error_exit(f"failed to import rule pack '{name}': {exc}")
        try:
            checker.load_rule_pack(module)
        except (AttributeError, TypeError) as exc:
            error_exit(f"failed to load rule pack '{name}': {exc}")


# ---------------------------------------------------------------------------
# Flag-group validation
# ---------------------------------------------------------------------------


def _resolve_types(
    type_flag: str | None,
    old_type_flag: str | None,
    new_type_flag: str | None,
) -> tuple[str, str]:
    """Determine the old and new fully-qualified type names.

    Callers must provide exactly one of:
      - ``--type NAME`` — same name on both sides.
      - ``--old-type A --new-type B`` — cross-type comparison.

    Args:
        type_flag: Value of ``--type`` (or ``None`` if unset).
        old_type_flag: Value of ``--old-type`` (or ``None``).
        new_type_flag: Value of ``--new-type`` (or ``None``).

    Returns:
        A ``(old_type, new_type)`` pair with both strings resolved.

    Raises:
        SystemExit: Via ``error_exit`` when neither or both modes
            are specified, or when cross-type mode is missing one
            half.
    """
    has_single = type_flag is not None
    has_cross = old_type_flag is not None or new_type_flag is not None

    if has_single and has_cross:
        error_exit(
            "Cannot combine --type with --old-type/--new-type. "
            "Use --type for same-name checks or --old-type + --new-type "
            "for cross-type checks."
        )
    if has_single:
        return type_flag, type_flag
    if has_cross:
        if old_type_flag is None or new_type_flag is None:
            error_exit(
                "Cross-type mode requires both --old-type and --new-type."
            )
        return old_type_flag, new_type_flag
    error_exit(
        "No message type specified. Use --type NAME for same-name checks "
        "or --old-type OLD --new-type NEW for cross-type checks."
    )


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------


_SEVERITY_COLORS: dict[Severity, str] = {
    Severity.WIRE: "red",
    Severity.SEMANTIC: "yellow",
    Severity.POLICY: "magenta",
}


def _format_finding_human(finding: Finding) -> str:
    """Render one finding as a colored, single-line string.

    Args:
        finding: The ``Finding`` to render.

    Returns:
        An ANSI-colored string suitable for terminal display. The
        severity is color-coded (red/yellow/magenta) and the rule_id
        appears in parentheses at the end.
    """
    color = _SEVERITY_COLORS[finding.severity]
    tag = click.style(
        f"[{finding.severity.value}/{finding.direction.value}]",
        fg=color,
        bold=True,
    )
    path_str = str(finding.path) if finding.path else "(root)"
    path_styled = click.style(path_str, bold=True)
    rule = click.style(f"({finding.rule_id})", fg="cyan")
    return f"  {tag} {path_styled}: {finding.message} {rule}"


def _render_human(report: CompatibilityReport) -> str:
    """Render a human-readable summary of the report.

    Args:
        report: The ``CompatibilityReport`` to render.

    Returns:
        A multi-line string. Header names the profile; body lists
        each finding; trailer shows the verdict (COMPATIBLE or
        INCOMPATIBLE in color).
    """
    lines = []
    header = (
        f"protokit compat — level: {report.level.value}, "
        f"{len(report)} finding(s)"
    )
    lines.append(click.style(header, bold=True))

    for finding in report:
        lines.append(_format_finding_human(finding))

    if report.is_compatible:
        verdict = click.style("COMPATIBLE", fg="green", bold=True)
    else:
        verdict = click.style("INCOMPATIBLE", fg="red", bold=True)
    lines.append("")
    lines.append(verdict)
    return "\n".join(lines)


def _render_json(report: CompatibilityReport) -> str:
    """Render the report as JSON matching the design-doc schema.

    Args:
        report: The ``CompatibilityReport`` to render.

    Returns:
        A pretty-printed JSON string with keys ``compatible``,
        ``level``, ``findings`` (list of objects with ``path``,
        ``rule_id``, ``severity``, ``direction``, ``message``), and
        ``summary`` (wire_breaks / semantic_breaks / policy_breaks /
        total counts).
    """
    payload: dict[str, Any] = {
        "compatible": report.is_compatible,
        "level": report.level.value,
        "findings": [
            {
                "path": str(f.path),
                "rule_id": f.rule_id,
                "severity": f.severity.value,
                "direction": f.direction.value,
                "message": f.message,
            }
            for f in report.findings
        ],
        "diagnostics": [
            {"level": d.level, "path": d.path, "message": d.message}
            for d in report.diagnostics
        ],
        "summary": {
            "wire_breaks": len(report.wire_breaks),
            "semantic_breaks": len(report.semantic_breaks),
            "policy_breaks": len(report.policy_breaks),
            "total": len(report),
        },
    }
    return json.dumps(payload, indent=2)


# ---------------------------------------------------------------------------
# Pool loaders (per mode)
# ---------------------------------------------------------------------------


def _load_pools_local(
    old_input: Path | None,
    new_input: Path | None,
    *,
    use_proto: bool,
    proto_paths: tuple[str, ...],
) -> tuple[descriptor_pool.DescriptorPool, descriptor_pool.DescriptorPool]:
    """Load two pools from local files (descriptor sets or .proto)."""
    if old_input is None or new_input is None:
        error_exit(
            "OLD_INPUT and NEW_INPUT are required without --since or "
            "--against-base."
        )
    if use_proto:
        return (
            compile_proto(old_input, proto_paths),
            compile_proto(new_input, proto_paths),
        )
    if proto_paths:
        error_exit("--proto-path only applies with --proto.")
    return (
        _safe_load_pool(old_input, label="OLD_INPUT"),
        _safe_load_pool(new_input, label="NEW_INPUT"),
    )


def _verify_proto_file_at_ref(
    proto_file: str,
    ref: str,
    proto_roots: tuple[str, ...],
    *,
    cwd: Path | None = None,
) -> None:
    """Pre-flight check: does ``proto_file`` exist at ``ref``?

    Gives the user a clean "proto_file not found at ref" error
    before the extraction pipeline dives into dep-walking and
    hands back a less-obvious ``ProtoImportError``. Run against
    the user-facing endpoint (typically HEAD or NEW) so typos
    surface before any historical-ref extraction starts.
    """
    from protokit.schema.git import _git_show  # avoid module-top circular

    for root in proto_roots:
        clean_root = root.rstrip("/")
        repo_path = (
            f"{clean_root}/{proto_file}"
            if clean_root and clean_root != "."
            else proto_file
        )
        try:
            _git_show(ref, repo_path, cwd=cwd)
            return  # found under some root
        except FileNotFoundError:
            continue
        except GitRefNotFoundError:
            # ref itself is bogus — let the main pipeline produce
            # that error; we're here to validate the path.
            return
    error_exit(
        f"--proto-file {proto_file!r} not found at ref {ref!r} "
        f"under any of the configured --proto-root paths "
        f"({list(proto_roots)!r}). Check the path and try again."
    )


def _validate_git_mode_flags(
    *,
    since: str | None,
    against_base: str | None,
    proto_file: str | None,
) -> None:
    """Reject malformed ``--since`` / ``--against-base`` flag combos.

    Two invariants:

    - ``--since`` and ``--against-base`` are mutually exclusive
      (each picks a different old-ref strategy).
    - Either flag requires ``--proto-file`` — without it we
      have no schema anchor to compare at the chosen ref.

    Called twice per ``check`` invocation on purpose: once from
    the subcommand body (early — so the error beats generic
    ``--type`` resolution) and once from :func:`_load_pools_git`
    (defensive — library users who call the loader directly
    still get the same guardrail). Idempotent: both calls run
    before any side effects, so the duplication costs nothing
    observable and lets either entry point stand alone.
    """
    if since is not None and against_base is not None:
        error_exit(
            "--since and --against-base are mutually exclusive."
        )
    if proto_file is None:
        error_exit(
            "--since / --against-base require --proto-file PATH."
        )


def _load_pools_git(
    *,
    since: str | None,
    against_base: str | None,
    proto_file: str | None,
    proto_roots: tuple[str, ...],
    cwd: Path | None = None,
    base_flag_hint: str = "--against-base",
) -> tuple[descriptor_pool.DescriptorPool, descriptor_pool.DescriptorPool, str, str]:
    """Resolve a (old_ref, new_ref) pair from git flags and extract pools.

    Returns ``(old_pool, new_pool, old_ref, new_ref)`` so callers
    can include the resolved refs in user-facing output.

    ``base_flag_hint`` is the CLI flag name the caller exposes for
    the base branch — spliced into the auto-resolve failure
    message so ``ci`` users see ``--base`` and ``check`` users see
    ``--against-base``.
    """
    _validate_git_mode_flags(
        since=since, against_base=against_base, proto_file=proto_file,
    )

    if since is not None:
        if not verify_ref(since, cwd=cwd):
            error_exit(f"unknown git ref: {since!r}")
        old_ref, new_ref = since, "HEAD"
    else:
        # against_base mode. Empty string sentinel = auto-resolve.
        if against_base == "":
            try:
                base = resolve_default_base(
                    cwd=cwd, flag_hint=base_flag_hint,
                )
            except GitRefNotFoundError as exc:
                error_exit(str(exc))
        else:
            assert against_base is not None
            if not verify_ref(against_base, cwd=cwd):
                error_exit(f"unknown git ref: {against_base!r}")
            base = against_base
        try:
            old_ref = merge_base("HEAD", base, cwd=cwd)
        except (GitRefNotFoundError, ShallowRepoError) as exc:
            error_exit(str(exc))
        new_ref = "HEAD"

    # Pre-flight: verify --proto-file actually exists at the
    # user-facing endpoint (NEW ref) before we start extracting.
    # A typoed path otherwise surfaces as a deep ProtoImportError;
    # the pre-check gives a one-line, actionable message.
    _verify_proto_file_at_ref(proto_file, new_ref, proto_roots, cwd=cwd)

    try:
        old_pool = extract_pool_from_ref(
            old_ref, proto_file, proto_roots=proto_roots, cwd=cwd,
        )
        new_pool = extract_pool_from_ref(
            new_ref, proto_file, proto_roots=proto_roots, cwd=cwd,
        )
    except (GitRefNotFoundError, ProtoImportError) as exc:
        error_exit(str(exc))
    return old_pool, new_pool, old_ref, new_ref


# ---------------------------------------------------------------------------
# Shared checker construction
# ---------------------------------------------------------------------------


def _resolve_range_endpoints(range_spec: str) -> tuple[str, str]:
    """Resolve the endpoints of a ``OLD..NEW`` range to fixed SHAs.

    Useful for JSON output: ``range`` carries what the user
    typed, while ``old`` / ``new`` carry the resolved SHAs so
    the payload remains meaningful after the named refs move.

    Raises:
        SystemExit: via ``error_exit`` if ``range_spec`` lacks
            ``..`` or either side fails to resolve.
    """
    # Support both two-dot and three-dot forms; we only need the
    # endpoints, and ``A...B`` is just a different walk semantics.
    if "..." in range_spec:
        sep = "..."
    elif ".." in range_spec:
        sep = ".."
    else:
        error_exit(
            f"invalid --range {range_spec!r}: expected OLD..NEW form"
        )
    parts = range_spec.split(sep, 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        error_exit(
            f"invalid --range {range_spec!r}: both endpoints required"
        )
    old_name, new_name = parts
    try:
        import subprocess
        old_sha = subprocess.run(
            ["git", "rev-parse", old_name],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        new_sha = subprocess.run(
            ["git", "rev-parse", new_name],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        error_exit(
            f"could not resolve range endpoints {range_spec!r}: {stderr}"
        )
    return old_sha, new_sha


def _reject_quiet_plus_json(*, quiet: bool, output_format: str) -> None:
    """Refuse ``--quiet --format json`` — the combination is
    ambiguous and pre-fix produced empty stdout, breaking CI
    consumers that expected to parse JSON.

    Semantically contradictory: ``--quiet`` says "no stdout",
    ``--format json`` asks for structured stdout. Fail loudly so
    users pick one.
    """
    if quiet and output_format.lower() == "json":
        error_exit(
            "--quiet and --format json are mutually exclusive: "
            "one suppresses stdout, the other asks for structured "
            "output. Pick one."
        )


def _resolve_common_flags(
    *,
    quiet: bool,
    output_format: str,
    type_flag: str | None,
    old_type: str | None,
    new_type: str | None,
    level_flag: str,
) -> tuple[str, str, CompatibilityLevel]:
    """Validate the subcommand-shared flag group and resolve derived values.

    Every subcommand opens with the same three-step prologue:

    1. Reject ``--quiet --format json`` (mutually exclusive —
       quiet suppresses stdout, JSON expects structured stdout).
    2. Resolve ``--type`` / ``--old-type`` / ``--new-type`` into
       the ``(old, new)`` type-name pair.
    3. Parse ``--level`` into a :class:`CompatibilityLevel`.

    Exit-priority is intentional: the ``--quiet/--format`` check
    is cheapest and points at the most likely user typo, so it
    runs first. The ``check`` subcommand interleaves
    mode-specific checks between steps 1 and 2 and therefore
    doesn't call this helper — see the subcommand body.
    """
    _reject_quiet_plus_json(quiet=quiet, output_format=output_format)
    old_type_name, new_type_name = _resolve_types(type_flag, old_type, new_type)
    level = _resolve_level(level_flag.lower())
    return old_type_name, new_type_name, level


def _build_configured_checker(
    *,
    level: CompatibilityLevel,
    rule_packs: tuple[str, ...] = (),
    ignore_paths: tuple[str, ...] = (),
    dedupe_by_type: bool = False,
) -> SchemaChecker:
    """Build a :class:`SchemaChecker` from CLI flag values.

    Shared by every subcommand so ``--rule-pack`` / ``--ignore``
    / ``--dedupe-by-type`` behave identically across
    ``check`` / ``history`` / ``bisect`` / ``ci``. Any invalid
    input surfaces via ``error_exit`` (exit 2) so the caller
    never has to branch on it.
    """
    checker = SchemaChecker(level=level, dedupe_by_type=dedupe_by_type)
    _load_rule_packs(checker, rule_packs)
    for path in ignore_paths:
        try:
            checker.ignore(path)
        except ValueError as exc:
            error_exit(f"invalid --ignore path {path!r}: {exc}")
    return checker


# ---------------------------------------------------------------------------
# Check pipeline (shared by check / ci)
# ---------------------------------------------------------------------------


def _run_check_pipeline(
    *,
    old_pool: descriptor_pool.DescriptorPool,
    new_pool: descriptor_pool.DescriptorPool,
    old_type: str,
    new_type: str,
    level: CompatibilityLevel,
    rule_packs: tuple[str, ...],
    ignore_paths: tuple[str, ...],
    dedupe_by_type: bool,
    output_format: str,
    quiet: bool,
    header: str | None = None,
) -> CompatibilityReport:
    """Run the configured checker, render output, and ``sys.exit``.

    Used by ``check`` and ``ci``. Returns the report (so subcommands
    that need it for further work can read it before the exit), but
    always calls ``sys.exit`` at the end with the conventional
    code (0/1/2).
    """
    checker = _build_configured_checker(
        level=level,
        rule_packs=rule_packs,
        ignore_paths=ignore_paths,
        dedupe_by_type=dedupe_by_type,
    )

    try:
        report = checker.check(old_pool, old_type, new_pool, new_type)
    except ValueError as exc:
        error_exit(str(exc))

    # Diagnostics stream to stderr regardless of --quiet. Errors
    # (tool-level failures — plugin crashes) and warnings
    # (comparison caveats) share the exit-2 contract but render
    # with different prefixes so operators can triage.
    for d in report.diagnostics:
        prefix = "Error:" if d.level == "error" else "Warning:"
        click.echo(f"{prefix} {d}", err=True)

    if not quiet:
        if header:
            click.echo(header)
        if output_format.lower() == "json":
            click.echo(_render_json(report))
        else:
            click.echo(_render_human(report))

    if report.diagnostics:
        sys.exit(2)
    sys.exit(0 if report.is_compatible else 1)


# ---------------------------------------------------------------------------
# Click group
# ---------------------------------------------------------------------------


@click.group()
def main() -> None:
    """Schema compatibility checks across descriptor sets, .proto sources, or git refs.

    EXIT CODES (uniform across subcommands):
        0 = compatible, 1 = incompatible, 2 = error.
    """


# ---------------------------------------------------------------------------
# `check` subcommand
# ---------------------------------------------------------------------------


@main.command("check")
@click.argument(
    "old_input",
    required=False,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.argument(
    "new_input",
    required=False,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--since",
    default=None,
    metavar="REF",
    help="Compare current HEAD against this git ref. Mutually "
         "exclusive with positional inputs and with --against-base. "
         "Requires --proto-file.",
)
@click.option(
    "--against-base",
    is_flag=False,
    flag_value="",
    default=None,
    metavar="[BRANCH]",
    help="Compare HEAD against the merge-base with BRANCH. With no "
         "argument, resolves @{upstream} → origin/main → "
         "origin/master in order. Mutually exclusive with --since "
         "and positional inputs. Requires --proto-file.",
)
@click.option(
    "--proto-file",
    default=None,
    metavar="PATH",
    help="Import-relative path of the root .proto file. Required "
         "with --since / --against-base; ignored otherwise.",
)
@click.option(
    "--proto-root",
    "proto_roots",
    multiple=True,
    default=(".",),
    show_default=True,
    metavar="DIR",
    help="Repository prefix for .proto import resolution "
         "(repeatable). Analogous to protoc -I. Only applies to "
         "--since / --against-base.",
)
@click.option(
    "--type",
    "type_flag",
    default=None,
    metavar="NAME",
    help="Fully-qualified message type name (same on both sides).",
)
@click.option(
    "--old-type",
    default=None,
    metavar="NAME",
    help="Fully-qualified type name in OLD_INPUT (cross-type mode).",
)
@click.option(
    "--new-type",
    default=None,
    metavar="NAME",
    help="Fully-qualified type name in NEW_INPUT (cross-type mode).",
)
@click.option(
    "--proto",
    "use_proto",
    is_flag=True,
    default=False,
    help="Treat OLD_INPUT and NEW_INPUT as .proto source files "
         "(compiled via protoxy / protoc).",
)
@click.option(
    "--proto-path",
    "-I",
    "proto_paths",
    multiple=True,
    metavar="DIR",
    help="Import path for the local --proto compilation "
         "(repeatable). Only applies with --proto.",
)
@click.option(
    "--level",
    "level_flag",
    type=click.Choice(_LEVEL_CHOICES, case_sensitive=False),
    default="consumer-safe",
    show_default=True,
    help="Compatibility profile controlling which findings surface.",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(("human", "json"), case_sensitive=False),
    default="human",
    show_default=True,
    help="Output format.",
)
@click.option(
    "--rule-pack",
    "rule_packs",
    multiple=True,
    metavar="MODULE",
    help="Python module exposing a RULES list of (rule_id, plugin_fn) "
         "pairs (repeatable).",
)
@click.option(
    "--ignore",
    "ignore_paths",
    multiple=True,
    metavar="PATH",
    help="Suppress findings at this dotted path prefix (repeatable).",
)
@click.option(
    "--dedupe-by-type",
    is_flag=True,
    default=False,
    help="Emit findings for each shared nested type only once "
         "(original behavior). Default is path-complete: findings "
         "appear at every path where the type is referenced.",
)
@click.option(
    "--quiet",
    is_flag=True,
    default=False,
    help="Suppress output; return exit code only.",
)
def check(
    old_input: Path | None,
    new_input: Path | None,
    since: str | None,
    against_base: str | None,
    proto_file: str | None,
    proto_roots: tuple[str, ...],
    type_flag: str | None,
    old_type: str | None,
    new_type: str | None,
    use_proto: bool,
    proto_paths: tuple[str, ...],
    level_flag: str,
    output_format: str,
    rule_packs: tuple[str, ...],
    ignore_paths: tuple[str, ...],
    dedupe_by_type: bool,
    quiet: bool,
) -> None:
    """Check schema compatibility between two protobuf schemas.

    Three modes:

    \b
    1. Local files (default):
        protokit compat check OLD.descriptor_set NEW.descriptor_set --type X
        protokit compat check OLD.proto NEW.proto --proto -I dir/ --type X

    \b
    2. Git --since:
        protokit compat check --since HEAD~5 --proto-file acme/user.proto --type X

    \b
    3. Git --against-base:
        protokit compat check --against-base origin/main --proto-file acme/user.proto --type X
        protokit compat check --against-base --proto-file acme/user.proto --type X
            # auto-resolves @{upstream} → origin/main → origin/master
    """
    # --------------------------------------------------------------
    # Structural validation first — fail with the most
    # mode-specific, actionable error before falling through to
    # generic type / level checks. A user who forgot both
    # --proto-file AND --type should see the mode-specific error
    # ("--since requires --proto-file") rather than the generic
    # "no message type specified", because the mode-specific one
    # points at the next thing they need to fix.
    # --------------------------------------------------------------
    _reject_quiet_plus_json(quiet=quiet, output_format=output_format)
    git_mode = since is not None or against_base is not None
    if git_mode and (old_input is not None or new_input is not None):
        error_exit(
            "Positional inputs cannot be combined with --since / "
            "--against-base."
        )
    if git_mode:
        _validate_git_mode_flags(
            since=since, against_base=against_base, proto_file=proto_file,
        )
    # --proto / --proto-path are local-mode flags. Reject early in
    # git mode so a silent no-op doesn't confuse users.
    if git_mode and use_proto:
        error_exit("--proto only applies in local-file mode.")
    if git_mode and proto_paths:
        error_exit(
            "--proto-path / -I only applies in local-file mode; "
            "use --proto-root for git-mode import search."
        )

    # Generic argument resolution runs AFTER mode-specific checks.
    old_type_name, new_type_name = _resolve_types(type_flag, old_type, new_type)
    level = _resolve_level(level_flag.lower())

    if git_mode:
        old_pool, new_pool, old_ref, new_ref = _load_pools_git(
            since=since, against_base=against_base,
            proto_file=proto_file, proto_roots=proto_roots,
        )
        header = (
            f"# protokit compat check: {old_ref} -> {new_ref} "
            f"({proto_file})"
        ) if not quiet and output_format.lower() != "json" else None
    else:
        old_pool, new_pool = _load_pools_local(
            old_input, new_input,
            use_proto=use_proto, proto_paths=proto_paths,
        )
        header = None

    _run_check_pipeline(
        old_pool=old_pool, new_pool=new_pool,
        old_type=old_type_name, new_type=new_type_name,
        level=level,
        rule_packs=rule_packs, ignore_paths=ignore_paths,
        dedupe_by_type=dedupe_by_type,
        output_format=output_format, quiet=quiet,
        header=header,
    )


# ---------------------------------------------------------------------------
# `history` subcommand
# ---------------------------------------------------------------------------


@main.command("history")
@click.option(
    "--range",
    "range_spec",
    required=True,
    metavar="OLD..NEW",
    help="Git revision range (e.g. ``HEAD~20..HEAD``).",
)
@click.option(
    "--proto-file",
    required=True,
    metavar="PATH",
    help="Import-relative path of the .proto file to track.",
)
@click.option(
    "--proto-root",
    "proto_roots",
    multiple=True,
    default=(".",),
    show_default=True,
    metavar="DIR",
    help="Repository prefix for .proto import resolution (repeatable).",
)
@click.option(
    "--type",
    "type_flag",
    default=None,
    metavar="NAME",
    help="Message type to track (same name on both sides).",
)
@click.option(
    "--old-type",
    default=None,
    metavar="NAME",
    help="Type name on the OLD side of each pair (cross-type mode).",
)
@click.option(
    "--new-type",
    default=None,
    metavar="NAME",
    help="Type name on the NEW side of each pair (cross-type mode).",
)
@click.option(
    "--level",
    "level_flag",
    type=click.Choice(_LEVEL_CHOICES, case_sensitive=False),
    default="consumer-safe",
    show_default=True,
    help="Compatibility profile.",
)
@click.option(
    "--rule-pack",
    "rule_packs",
    multiple=True,
    metavar="MODULE",
    help="Python module exposing a RULES list of (rule_id, plugin_fn) "
         "pairs (repeatable). Applied to every pair in the walk.",
)
@click.option(
    "--ignore",
    "ignore_paths",
    multiple=True,
    metavar="PATH",
    help="Suppress findings at this dotted path prefix (repeatable).",
)
@click.option(
    "--dedupe-by-type",
    is_flag=True,
    default=False,
    help="Emit findings for each shared nested type only once per pair "
         "(original behavior). Default is path-complete.",
)
@click.option(
    "--fast",
    is_flag=True,
    default=False,
    help="Use the fast dep-tree enumeration (E+): unions dep "
         "graphs at range endpoints and does per-path "
         "`git log --follow`. Tracks renames. Misses commits "
         "that modified a dep which was live only mid-range — "
         "rare. Default is the exact enumeration (D): walks every "
         ".proto-touching commit and filters by per-ref dep tree. "
         "See README §bisect-accuracy for the full tradeoff.",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(("human", "json"), case_sensitive=False),
    default="human",
    show_default=True,
    help="Output format.",
)
@click.option(
    "--quiet",
    is_flag=True,
    default=False,
    help="Suppress stdout; return exit code only. Diagnostics "
         "still stream to stderr.",
)
def history(
    range_spec: str,
    proto_file: str,
    proto_roots: tuple[str, ...],
    type_flag: str | None,
    old_type: str | None,
    new_type: str | None,
    level_flag: str,
    rule_packs: tuple[str, ...],
    ignore_paths: tuple[str, ...],
    dedupe_by_type: bool,
    fast: bool,
    output_format: str,
    quiet: bool,
) -> None:
    """Walk commits in OLD..NEW that touch the .proto and report findings per pair.

    For each consecutive (parent, child) pair of commits in the
    range that touched ``--proto-file``, runs a compatibility
    check and emits the findings tagged with the child SHA.

    Exits 0 if no commit in the range produced a finding under
    the chosen profile; 1 if any did; 2 on a hard error
    (unknown ref, missing import, any diagnostic from the
    registered plugins).
    """
    old_type_name, new_type_name, level = _resolve_common_flags(
        quiet=quiet, output_format=output_format,
        type_flag=type_flag, old_type=old_type, new_type=new_type,
        level_flag=level_flag,
    )

    # Resolve the range's endpoints to fixed SHAs. These appear in
    # the JSON payload so a downstream tool can pin the exact
    # commits this walk examined — important when the range was
    # specified as moving names like ``HEAD~20..HEAD``.
    old_endpoint, new_endpoint = _resolve_range_endpoints(range_spec)

    try:
        commits = commits_affecting_dep_tree(
            range_spec, proto_file, proto_roots,
            fast=fast,
        )
    except GitRefNotFoundError as exc:
        error_exit(str(exc))

    if not commits:
        if not quiet:
            if output_format.lower() == "json":
                click.echo(json.dumps({
                    "range": range_spec,
                    "old": old_endpoint,
                    "new": new_endpoint,
                    "commits_walked": 0,
                    "entries": [],
                    "diagnostics": [],
                }, indent=2))
            else:
                click.echo(f"# {range_spec}: no commits touch {proto_file}")
        sys.exit(0)

    # Anchor: the parent of the oldest commit in the range. Without it
    # the first entry would have nothing to compare against.
    anchor = f"{commits[0]}^"
    if not verify_ref(anchor):
        error_exit(
            f"could not resolve parent of {commits[0]} — the range "
            "may include the repository root"
        )

    pairs: list[tuple[str, str]] = []
    prev = anchor
    for sha in commits:
        pairs.append((prev, sha))
        prev = sha

    entries: list[dict[str, Any]] = []
    aggregated_diagnostics: list[dict[str, Any]] = []
    any_findings = False
    any_diagnostics = False
    for old_ref, new_ref in pairs:
        try:
            old_pool = extract_pool_from_ref(
                old_ref, proto_file, proto_roots=proto_roots,
            )
            new_pool = extract_pool_from_ref(
                new_ref, proto_file, proto_roots=proto_roots,
            )
        except (GitRefNotFoundError, ProtoImportError) as exc:
            error_exit(str(exc))

        # Fresh checker per pair so rule-pack plugin state doesn't
        # leak findings across commits.
        checker = _build_configured_checker(
            level=level,
            rule_packs=rule_packs,
            ignore_paths=ignore_paths,
            dedupe_by_type=dedupe_by_type,
        )
        try:
            report = checker.check(
                old_pool, old_type_name, new_pool, new_type_name,
            )
        except ValueError as exc:
            error_exit(str(exc))

        if report.diagnostics:
            any_diagnostics = True
            for d in report.diagnostics:
                prefix = "Error" if d.level == "error" else "Warning"
                click.echo(f"{prefix} ({new_ref[:12]}): {d}", err=True)
                aggregated_diagnostics.append({
                    "commit": new_ref,
                    "level": d.level,
                    "path": d.path,
                    "message": d.message,
                })
        if report.findings:
            any_findings = True

        entries.append({
            "old": old_ref,
            "new": new_ref,
            "compatible": report.is_compatible,
            "findings": [
                {
                    "path": str(f.path),
                    "rule_id": f.rule_id,
                    "severity": f.severity.value,
                    "direction": f.direction.value,
                    "message": f.message,
                }
                for f in report.findings
            ],
            "diagnostics": [
                {"level": d.level, "path": d.path, "message": d.message}
                for d in report.diagnostics
            ],
        })

    if not quiet:
        if output_format.lower() == "json":
            click.echo(json.dumps({
                "range": range_spec,
                "old": old_endpoint,
                "new": new_endpoint,
                "commits_walked": len(commits),
                "entries": entries,
                "diagnostics": aggregated_diagnostics,
            }, indent=2))
        else:
            for entry in entries:
                short = entry["new"][:12]
                verdict = "OK" if entry["compatible"] else "BROKEN"
                click.echo(f"{short} {verdict} ({len(entry['findings'])} finding(s))")
                for f in entry["findings"]:
                    click.echo(
                        f"    [{f['severity']}/{f['direction']}] "
                        f"{f['path']}: {f['message']} ({f['rule_id']})"
                    )

    if any_diagnostics:
        sys.exit(2)
    sys.exit(1 if any_findings else 0)


# ---------------------------------------------------------------------------
# `bisect` subcommand
# ---------------------------------------------------------------------------


@main.command("bisect")
@click.option(
    "--old",
    "old_ref",
    required=True,
    metavar="REF",
    help="Old (compatible) endpoint of the bisect range.",
)
@click.option(
    "--new",
    "new_ref",
    required=True,
    metavar="REF",
    help="New (broken) endpoint of the bisect range.",
)
@click.option(
    "--proto-file",
    required=True,
    metavar="PATH",
    help="Import-relative path of the .proto file to track.",
)
@click.option(
    "--proto-root",
    "proto_roots",
    multiple=True,
    default=(".",),
    show_default=True,
    metavar="DIR",
    help="Repository prefix for .proto import resolution (repeatable).",
)
@click.option(
    "--type",
    "type_flag",
    default=None,
    metavar="NAME",
    help="Message type to bisect against (same name on both sides).",
)
@click.option(
    "--old-type",
    default=None,
    metavar="NAME",
    help="Type name on the OLD side (cross-type mode).",
)
@click.option(
    "--new-type",
    default=None,
    metavar="NAME",
    help="Type name on the NEW side (cross-type mode).",
)
@click.option(
    "--level",
    "level_flag",
    type=click.Choice(_LEVEL_CHOICES, case_sensitive=False),
    default="consumer-safe",
    show_default=True,
    help="Compatibility profile.",
)
@click.option(
    "--rule-pack",
    "rule_packs",
    multiple=True,
    metavar="MODULE",
    help="Python module exposing a RULES list of (rule_id, plugin_fn) "
         "pairs (repeatable). Applied at every commit in the walk.",
)
@click.option(
    "--ignore",
    "ignore_paths",
    multiple=True,
    metavar="PATH",
    help="Suppress findings at this dotted path prefix (repeatable).",
)
@click.option(
    "--dedupe-by-type",
    is_flag=True,
    default=False,
    help="Emit findings for each shared nested type only once per pair "
         "(original behavior). Default is path-complete.",
)
@click.option(
    "--keep-going",
    is_flag=True,
    default=False,
    help="Walk every commit in the range even after hitting a "
         "diagnostic or a break. Without this flag the walk stops "
         "at the first anomaly — faster feedback but forces extra "
         "CI runs when multiple independent issues exist. With the "
         "flag, you get the full picture in one run; exit code "
         "still dominates on diagnostics.",
)
@click.option(
    "--fast",
    is_flag=True,
    default=False,
    help="Use the fast dep-tree enumeration (E+): unions dep "
         "graphs at range endpoints and does per-path "
         "`git log --follow`. Tracks renames. Misses commits "
         "that modified a dep which was live only mid-range — "
         "rare. Default is the exact enumeration (D): walks every "
         ".proto-touching commit and filters by per-ref dep tree. "
         "See README §bisect-accuracy for the full tradeoff.",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(("human", "json"), case_sensitive=False),
    default="human",
    show_default=True,
    help="Output format.",
)
@click.option(
    "--quiet",
    is_flag=True,
    default=False,
    help="Suppress stdout; return exit code only. Diagnostics "
         "still stream to stderr.",
)
def bisect(
    old_ref: str,
    new_ref: str,
    proto_file: str,
    proto_roots: tuple[str, ...],
    type_flag: str | None,
    old_type: str | None,
    new_type: str | None,
    level_flag: str,
    rule_packs: tuple[str, ...],
    ignore_paths: tuple[str, ...],
    dedupe_by_type: bool,
    keep_going: bool,
    fast: bool,
    output_format: str,
    quiet: bool,
) -> None:
    """Find the earliest commit in OLD..NEW that broke compatibility.

    Linearly walks the .proto-touching commits in the range and
    reports the first one whose pool produces a finding against
    the OLD ref's pool. Linear (not binary) because the engine
    is fast and the user-visible cost of a misclassification at
    the wrong commit is high — exact attribution beats latency.

    Exit codes:
        0 = no break found in the range (--old and --new are both compatible).
        1 = found the breaking commit; SHA printed to stdout.
        2 = hard error (unknown ref, missing import, any diagnostic
            from the registered plugins).
    """
    old_type_name, new_type_name, level = _resolve_common_flags(
        quiet=quiet, output_format=output_format,
        type_flag=type_flag, old_type=old_type, new_type=new_type,
        level_flag=level_flag,
    )

    if not verify_ref(old_ref):
        error_exit(f"unknown git ref: {old_ref!r}")
    if not verify_ref(new_ref):
        error_exit(f"unknown git ref: {new_ref!r}")

    # Resolve named refs to SHAs for the JSON payload — the
    # ``old`` / ``new`` keys in output should pin exactly what
    # this run examined, even if ``HEAD`` or a branch moves
    # before the next invocation.
    old_sha, new_sha = _resolve_range_endpoints(f"{old_ref}..{new_ref}")

    try:
        commits = commits_affecting_dep_tree(
            f"{old_ref}..{new_ref}", proto_file, proto_roots,
            fast=fast,
        )
    except GitRefNotFoundError as exc:
        error_exit(str(exc))

    json_mode = output_format.lower() == "json"

    def _emit_and_exit(
        *,
        breaking_commit: str | None,
        breaking_findings: list,
        diagnostics_payload: list[dict[str, Any]],
        exit_code: int,
    ) -> None:
        """Render the final output and exit."""
        if quiet:
            sys.exit(exit_code)
        if json_mode:
            click.echo(json.dumps({
                "range": f"{old_ref}..{new_ref}",
                "old": old_sha,
                "new": new_sha,
                "breaking_commit": breaking_commit,
                "findings": [
                    {
                        "path": str(f.path),
                        "rule_id": f.rule_id,
                        "severity": f.severity.value,
                        "direction": f.direction.value,
                        "message": f.message,
                    }
                    for f in breaking_findings
                ],
                "commits_walked": len(commits),
                "diagnostics": diagnostics_payload,
            }, indent=2))
        else:
            if breaking_commit is not None:
                click.echo(f"first breaking commit: {breaking_commit}")
                for f in breaking_findings:
                    click.echo(f"  {f}")
            elif not commits:
                click.echo(
                    f"# {old_ref}..{new_ref}: no commits touch {proto_file}"
                )
            else:
                click.echo(
                    f"# {old_ref}..{new_ref}: no break found across "
                    f"{len(commits)} commit(s)"
                )
        sys.exit(exit_code)

    if not commits:
        _emit_and_exit(
            breaking_commit=None,
            breaking_findings=[],
            diagnostics_payload=[],
            exit_code=0,
        )

    try:
        anchor_pool = extract_pool_from_ref(
            old_ref, proto_file, proto_roots=proto_roots,
        )
    except (GitRefNotFoundError, ProtoImportError) as exc:
        error_exit(str(exc))

    # Accumulators — used by the --keep-going path AND the
    # JSON output shape so every invocation emits the same
    # top-level keys.
    diagnostics_payload: list[dict[str, Any]] = []
    any_diagnostics = False
    first_break_sha: str | None = None
    first_break_findings: list = []

    for sha in commits:
        try:
            new_pool = extract_pool_from_ref(
                sha, proto_file, proto_roots=proto_roots,
            )
        except (GitRefNotFoundError, ProtoImportError) as exc:
            error_exit(str(exc))
        checker = _build_configured_checker(
            level=level,
            rule_packs=rule_packs,
            ignore_paths=ignore_paths,
            dedupe_by_type=dedupe_by_type,
        )
        try:
            report = checker.check(
                anchor_pool, old_type_name, new_pool, new_type_name,
            )
        except ValueError as exc:
            error_exit(str(exc))

        if report.diagnostics:
            any_diagnostics = True
            for d in report.diagnostics:
                prefix = "Error" if d.level == "error" else "Warning"
                click.echo(f"{prefix} ({sha[:12]}): {d}", err=True)
                diagnostics_payload.append({
                    "commit": sha,
                    "level": d.level,
                    "path": d.path,
                    "message": d.message,
                })
            if not keep_going:
                # Stop-fast: assume the diagnostic invalidates any
                # subsequent result.
                _emit_and_exit(
                    breaking_commit=first_break_sha,
                    breaking_findings=first_break_findings,
                    diagnostics_payload=diagnostics_payload,
                    exit_code=2,
                )
        if report.findings and first_break_sha is None:
            first_break_sha = sha
            first_break_findings = list(report.findings)
            if not keep_going:
                _emit_and_exit(
                    breaking_commit=first_break_sha,
                    breaking_findings=first_break_findings,
                    diagnostics_payload=diagnostics_payload,
                    exit_code=1,
                )

    # Exit priority: diagnostics (2) > break (1) > clean (0).
    if any_diagnostics:
        exit_code = 2
    elif first_break_sha is not None:
        exit_code = 1
    else:
        exit_code = 0
    _emit_and_exit(
        breaking_commit=first_break_sha,
        breaking_findings=first_break_findings,
        diagnostics_payload=diagnostics_payload,
        exit_code=exit_code,
    )


# ---------------------------------------------------------------------------
# `ci` subcommand
# ---------------------------------------------------------------------------


@main.command("ci")
@click.option(
    "--base",
    "base_ref",
    default=None,
    metavar="BRANCH",
    help="Base branch to compare HEAD's merge-base against. Default "
         "auto-resolves @{upstream} → origin/main → origin/master.",
)
@click.option(
    "--proto-file",
    required=True,
    metavar="PATH",
    help="Import-relative path of the root .proto file.",
)
@click.option(
    "--proto-root",
    "proto_roots",
    multiple=True,
    default=(".",),
    show_default=True,
    metavar="DIR",
    help="Repository prefix for .proto import resolution (repeatable).",
)
@click.option(
    "--type",
    "type_flag",
    default=None,
    metavar="NAME",
    help="Message type (same on both sides).",
)
@click.option(
    "--old-type",
    default=None,
    metavar="NAME",
    help="Type name on the BASE side (cross-type mode).",
)
@click.option(
    "--new-type",
    default=None,
    metavar="NAME",
    help="Type name on the HEAD side (cross-type mode).",
)
@click.option(
    "--level",
    "level_flag",
    type=click.Choice(_LEVEL_CHOICES, case_sensitive=False),
    default="consumer-safe",
    show_default=True,
    help="Compatibility profile.",
)
@click.option(
    "--rule-pack",
    "rule_packs",
    multiple=True,
    metavar="MODULE",
    help="Python module exposing a RULES list of (rule_id, plugin_fn) "
         "pairs (repeatable).",
)
@click.option(
    "--ignore",
    "ignore_paths",
    multiple=True,
    metavar="PATH",
    help="Suppress findings at this dotted path prefix (repeatable).",
)
@click.option(
    "--dedupe-by-type",
    is_flag=True,
    default=False,
    help="Emit findings for each shared nested type only once "
         "(original behavior). Default is path-complete.",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(("human", "json"), case_sensitive=False),
    default="human",
    show_default=True,
    help="Output format.",
)
@click.option(
    "--quiet",
    is_flag=True,
    default=False,
    help="Suppress stdout; return exit code only. Diagnostics "
         "still stream to stderr.",
)
def ci(
    base_ref: str | None,
    proto_file: str,
    proto_roots: tuple[str, ...],
    type_flag: str | None,
    old_type: str | None,
    new_type: str | None,
    level_flag: str,
    rule_packs: tuple[str, ...],
    ignore_paths: tuple[str, ...],
    dedupe_by_type: bool,
    output_format: str,
    quiet: bool,
) -> None:
    """CI gate: compare HEAD against a base branch's merge-base.

    Equivalent to ``check --against-base BRANCH --proto-file
    PATH``, with required ``--proto-file`` and the same exit
    codes (0/1/2). Distinct subcommand because CI configs
    benefit from an unambiguous, non-overloaded entry point —
    no positional-arg shape, no mode-detection ambiguity, and
    a name that signals intent in pipeline yaml.
    """
    old_type_name, new_type_name, level = _resolve_common_flags(
        quiet=quiet, output_format=output_format,
        type_flag=type_flag, old_type=old_type, new_type=new_type,
        level_flag=level_flag,
    )

    # The CI subcommand always uses --against-base semantics. Reuse
    # the shared loader so the resolution rules stay identical.
    # Flag-hint tells the auto-resolver to mention ``--base`` (the
    # CI command's flag) in the failure message, not
    # ``--against-base``.
    against = "" if base_ref is None else base_ref
    old_pool, new_pool, old_ref, new_ref = _load_pools_git(
        since=None, against_base=against,
        proto_file=proto_file, proto_roots=proto_roots,
        base_flag_hint="--base",
    )
    header = (
        f"# protokit compat ci: {old_ref} -> {new_ref} ({proto_file})"
        if output_format.lower() != "json" else None
    )
    _run_check_pipeline(
        old_pool=old_pool, new_pool=new_pool,
        old_type=old_type_name, new_type=new_type_name,
        level=level,
        rule_packs=rule_packs,
        ignore_paths=ignore_paths,
        dedupe_by_type=dedupe_by_type,
        output_format=output_format, quiet=quiet,
        header=header,
    )
