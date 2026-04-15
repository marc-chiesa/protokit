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
        "warnings": [
            {"path": w.path, "message": w.message}
            for w in report.warnings
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
    if since is not None and against_base is not None:
        error_exit(
            "--since and --against-base are mutually exclusive."
        )
    if proto_file is None:
        error_exit(
            "--since / --against-base require --proto-file PATH."
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
    checker = SchemaChecker(level=level, dedupe_by_type=dedupe_by_type)
    _load_rule_packs(checker, rule_packs)
    for path in ignore_paths:
        try:
            checker.ignore(path)
        except ValueError as exc:
            error_exit(f"invalid --ignore path {path!r}: {exc}")

    try:
        report = checker.check(old_pool, old_type, new_pool, new_type)
    except ValueError as exc:
        error_exit(str(exc))

    if report.warnings:
        for w in report.warnings:
            click.echo(f"Warning: {w}", err=True)

    if not quiet:
        if header:
            click.echo(header)
        if output_format.lower() == "json":
            click.echo(_render_json(report))
        else:
            click.echo(_render_human(report))

    if report.warnings:
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
    git_mode = since is not None or against_base is not None
    if git_mode and (old_input is not None or new_input is not None):
        error_exit(
            "Positional inputs cannot be combined with --since / "
            "--against-base."
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
    "--format",
    "output_format",
    type=click.Choice(("human", "json"), case_sensitive=False),
    default="human",
    show_default=True,
    help="Output format.",
)
def history(
    range_spec: str,
    proto_file: str,
    proto_roots: tuple[str, ...],
    type_flag: str | None,
    old_type: str | None,
    new_type: str | None,
    level_flag: str,
    output_format: str,
) -> None:
    """Walk commits in OLD..NEW that touch the .proto and report findings per pair.

    For each consecutive (parent, child) pair of commits in the
    range that touched ``--proto-file``, runs a compatibility
    check and emits the findings tagged with the child SHA.

    Exits 0 if no commit in the range produced a finding under
    the chosen profile; 1 if any did; 2 on a hard error
    (unknown ref, missing import, plugin warning).
    """
    old_type_name, new_type_name = _resolve_types(type_flag, old_type, new_type)
    level = _resolve_level(level_flag.lower())

    try:
        commits = commits_in_range(range_spec, paths=[proto_file])
    except GitRefNotFoundError as exc:
        error_exit(str(exc))

    if not commits:
        if output_format.lower() == "json":
            click.echo(json.dumps({"range": range_spec, "entries": []}, indent=2))
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
    any_findings = False
    any_warnings = False
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

        checker = SchemaChecker(level=level)
        try:
            report = checker.check(
                old_pool, old_type_name, new_pool, new_type_name,
            )
        except ValueError as exc:
            error_exit(str(exc))

        if report.warnings:
            any_warnings = True
            for w in report.warnings:
                click.echo(f"Warning ({new_ref[:12]}): {w}", err=True)
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
        })

    if output_format.lower() == "json":
        click.echo(json.dumps({"range": range_spec, "entries": entries}, indent=2))
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

    if any_warnings:
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
def bisect(
    old_ref: str,
    new_ref: str,
    proto_file: str,
    proto_roots: tuple[str, ...],
    type_flag: str | None,
    old_type: str | None,
    new_type: str | None,
    level_flag: str,
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
        2 = hard error (unknown ref, missing import, plugin warning).
    """
    old_type_name, new_type_name = _resolve_types(type_flag, old_type, new_type)
    level = _resolve_level(level_flag.lower())

    if not verify_ref(old_ref):
        error_exit(f"unknown git ref: {old_ref!r}")
    if not verify_ref(new_ref):
        error_exit(f"unknown git ref: {new_ref!r}")

    try:
        commits = commits_in_range(
            f"{old_ref}..{new_ref}", paths=[proto_file],
        )
    except GitRefNotFoundError as exc:
        error_exit(str(exc))

    if not commits:
        click.echo(
            f"# {old_ref}..{new_ref}: no commits touch {proto_file}"
        )
        sys.exit(0)

    try:
        anchor_pool = extract_pool_from_ref(
            old_ref, proto_file, proto_roots=proto_roots,
        )
    except (GitRefNotFoundError, ProtoImportError) as exc:
        error_exit(str(exc))

    for sha in commits:
        try:
            new_pool = extract_pool_from_ref(
                sha, proto_file, proto_roots=proto_roots,
            )
        except (GitRefNotFoundError, ProtoImportError) as exc:
            error_exit(str(exc))
        checker = SchemaChecker(level=level)
        try:
            report = checker.check(
                anchor_pool, old_type_name, new_pool, new_type_name,
            )
        except ValueError as exc:
            error_exit(str(exc))
        if report.warnings:
            for w in report.warnings:
                click.echo(f"Warning ({sha[:12]}): {w}", err=True)
            sys.exit(2)
        if report.findings:
            click.echo(f"first breaking commit: {sha}")
            for f in report.findings:
                click.echo(f"  {f}")
            sys.exit(1)

    click.echo(
        f"# {old_ref}..{new_ref}: no break found across "
        f"{len(commits)} commit(s)"
    )
    sys.exit(0)


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
    "--format",
    "output_format",
    type=click.Choice(("human", "json"), case_sensitive=False),
    default="human",
    show_default=True,
    help="Output format.",
)
def ci(
    base_ref: str | None,
    proto_file: str,
    proto_roots: tuple[str, ...],
    type_flag: str | None,
    old_type: str | None,
    new_type: str | None,
    level_flag: str,
    output_format: str,
) -> None:
    """CI gate: compare HEAD against a base branch's merge-base.

    Equivalent to ``check --against-base BRANCH --proto-file
    PATH``, with required ``--proto-file`` and the same exit
    codes (0/1/2). Distinct subcommand because CI configs
    benefit from an unambiguous, non-overloaded entry point —
    no positional-arg shape, no mode-detection ambiguity, and
    a name that signals intent in pipeline yaml.
    """
    old_type_name, new_type_name = _resolve_types(type_flag, old_type, new_type)
    level = _resolve_level(level_flag.lower())

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
        rule_packs=(), ignore_paths=(),
        dedupe_by_type=False,
        output_format=output_format, quiet=False,
        header=header,
    )
