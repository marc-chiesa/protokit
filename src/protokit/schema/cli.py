"""Click CLI for ``protokit compat``.

Runs a schema compatibility check between two descriptor sets (or
two ``.proto`` files compiled on the fly) and reports findings under
a chosen compatibility profile.

Invocation shape (from the design doc)::

    protokit compat old.descriptor_set new.descriptor_set \
        --type mypackage.Message \
        --level consumer-safe \
        --format human|json \
        --rule-pack myorg.proto_rules \
        --ignore internal_debug_field

Exit codes:
    0 — compatible (no findings survived the profile filter)
    1 — incompatible (at least one finding survived)
    2 — error (bad flags, missing type, protoc failure, rule-pack load failure)
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
# Click command
# ---------------------------------------------------------------------------


@click.command()
@click.argument(
    "old_input",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.argument(
    "new_input",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
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
         "(compiled via protoc on PATH).",
)
@click.option(
    "--proto-path",
    "-I",
    "proto_paths",
    multiple=True,
    metavar="DIR",
    help="Import path for protoc (repeatable). Only used with --proto.",
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
    "--quiet",
    is_flag=True,
    default=False,
    help="Suppress output; return exit code only.",
)
def main(
    old_input: Path,
    new_input: Path,
    type_flag: str | None,
    old_type: str | None,
    new_type: str | None,
    use_proto: bool,
    proto_paths: tuple[str, ...],
    level_flag: str,
    output_format: str,
    rule_packs: tuple[str, ...],
    ignore_paths: tuple[str, ...],
    quiet: bool,
) -> None:
    """Check schema compatibility between two protobuf schemas.

    OLD_INPUT and NEW_INPUT are ``.descriptor_set`` files by default,
    or ``.proto`` source files when --proto is given. A single
    ``--type`` checks the same-named message on both sides; use
    ``--old-type`` with ``--new-type`` to compare messages with
    different fully-qualified names.

    EXIT CODES: 0 = compatible, 1 = incompatible, 2 = error.
    """
    old_type_name, new_type_name = _resolve_types(type_flag, old_type, new_type)
    level = _resolve_level(level_flag.lower())

    if use_proto:
        old_pool = compile_proto(old_input, proto_paths)
        new_pool = compile_proto(new_input, proto_paths)
    else:
        if proto_paths:
            error_exit("--proto-path only applies with --proto.")
        old_pool = _safe_load_pool(old_input, label="OLD_INPUT")
        new_pool = _safe_load_pool(new_input, label="NEW_INPUT")

    checker = SchemaChecker(level=level)
    _load_rule_packs(checker, rule_packs)
    for path in ignore_paths:
        try:
            checker.ignore(path)
        except ValueError as exc:
            error_exit(f"invalid --ignore path {path!r}: {exc}")

    try:
        report = checker.check(old_pool, old_type_name, new_pool, new_type_name)
    except ValueError as exc:
        error_exit(str(exc))

    # Plugin failures are fail-closed at the CLI layer: a broken
    # custom rule that was supposed to surface a finding must not
    # silently pass CI. Warnings always go to stderr; when any are
    # present the CLI exits with code 2 even if the filtered report
    # is empty.
    if report.warnings:
        for w in report.warnings:
            click.echo(f"Warning: {w}", err=True)

    if not quiet:
        if output_format.lower() == "json":
            click.echo(_render_json(report))
        else:
            click.echo(_render_human(report))

    if report.warnings:
        sys.exit(2)
    sys.exit(0 if report.is_compatible else 1)
