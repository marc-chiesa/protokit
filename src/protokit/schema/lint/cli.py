"""``protokit lint`` click subcommand — Delivery 3, Units 2 + 3.

Single-command click subcommand (NOT a sub-group; per origin R1).
Registered on the top-level ``protokit`` CLI group at
``src/protokit/cli.py``.

This module imports ``protokit.formatters._builtin_lint`` at module
top, which triggers the side-effect registration of the four lint
formatters (``lint_human`` shipped in U1; ``lint_json`` /
``lint_junit`` / ``lint_sarif`` land in U4b). Registration runs at
``protokit.cli`` load time — i.e., on every ``protokit ...``
invocation, regardless of which subcommand the user fires.

Cold-import contract: ``import protokit.schema`` does NOT
transitively load this module. The contract is preserved by NOT
adding ``_builtin_lint`` to ``formatters/__init__.py``'s eager-load
tuple. See origin's R3 + R15 for the full rationale.

U2 shipped the minimal end-to-end pipeline (descriptor-set + --proto
input modes; auto-load BUILTIN_PACKS; default profile derived via
LintProfile.from_pack; engine.run; lint_human render).

U3 (this unit) adds:
    1. ``--rule-pack MODULE`` (repeatable) — load user-supplied rule
       packs on top of BUILTIN_PACKS via ``importlib.import_module``.
    2. ``--profile NAME`` (default ``"default"``) — select which
       profile each pack contributes to the resolved set.
    3. ``--min-severity LEVEL`` — override the composed profile's
       severity floor; emits a stderr breadcrumb when the override
       is more lenient than the composed floor.
    4. R9 zero-rules loud failure (``error[lint-no-rules]:``).
    5. R11 unknown-profile loud failure (``error[lint-unknown-profile]:``)
       with per-pack introspection of declared profile names.
    6. R25 multi-pack composition stderr provenance line — gated on
       ``len(loaded_packs) >= 2`` (single-pack default emits no line
       per origin R25 revised).
    7. Runtime-warning emission — engine warnings (``rule_exception``,
       ``unloaded_rule``) surface as ``warning[lint-runtime]:`` lines
       on stderr after ``engine.run`` returns. Closes the agent-native
       silent-drop concern from U2's ce:review.
    8. Non-error compile diagnostics in ``--proto`` mode — info /
       warning level diagnostics from the protoxy/protoc backend
       surface to stderr alongside (or instead of) the
       ``compile-failed`` exit path.

U4a wires the R20 exit-code ladder + ``--max-warnings`` /
``--statistics`` / ``--quiet`` / ``--format``. U4b adds the three
machine formatters. Until U4a lands, exit code is 0 unconditionally
on successful pipeline runs (the KD-10 invariant requires only
"never 2 from internal CLI errors", which holds).
"""

from __future__ import annotations

import dataclasses
import sys
from collections import Counter
from pathlib import Path
from types import ModuleType

import click

# Importing ``lint_human`` registers all four lint formatters in the
# formatter registry as a side effect — the ``_builtin_lint`` module
# body runs ``_register_builtin`` calls at import time. This MUST
# happen at module top so registration runs at ``protokit.cli`` load
# time, before click dispatches the subcommand callback.
from protokit._cli_utils import _scrub_exc_message
from protokit.formatters import (
    FormatterContext,
    FormatterKind,
    get_formatter,
    list_formatters,
)
from protokit.formatters._builtin_lint import (
    lint_human,  # noqa: F401 -- import side-effect: registers lint formatters in the registry
)
from protokit.schema.compile import compile_protos_to_result
from protokit.schema.lint._cli_utils import (
    _active_rule_ids_per_pack,
    _declared_profiles_per_pack,
    _load_descriptor_sets_to_result,
    _load_user_rule_pack,
    _run_lint_formatter_safely,
    _safe_module_name,
    error_exit_with_code,
)
from protokit.schema.lint.engine import LintEngine
from protokit.schema.lint.model import (
    SEVERITY_RANK,
    DuplicateRuleError,
    LintProfile,
    LintReport,
    LintSeverity,
)
from protokit.schema.lint.rules import BUILTIN_PACKS

#: Mapping of click ``--min-severity`` choice values to ``LintSeverity``
#: enum members. ``click.Choice`` validates the input string before the
#: callback fires; the lookup here is total over the validated values.
_MIN_SEVERITY_CHOICES: dict[str, LintSeverity] = {
    "info": LintSeverity.INFO,
    "warning": LintSeverity.WARNING,
    "error": LintSeverity.ERROR,
}


@click.command(
    "lint",
    short_help="Lint a protobuf schema for style and policy violations.",
    epilog=(
        "EXAMPLES:\n\n"
        "  Lint a pre-built descriptor set:\n\n"
        "    protokit lint schema.descriptor_set\n\n"
        "  Lint .proto sources directly (compiled at invocation):\n\n"
        "    protokit lint --proto api.proto -I src/\n\n"
        "  Lint multiple descriptor sets merged into one pool:\n\n"
        "    protokit lint a.descriptor_set b.descriptor_set\n\n"
        "  Load a user rule pack on top of the built-in canary:\n\n"
        "    protokit lint --rule-pack acme.lint_rules schema.descriptor_set\n\n"
        "EXIT CODES (R20 ladder):\n\n"
        "  0 = clean run (no findings, or only INFO findings, or "
        "WARNINGs with --max-warnings unset / not exceeded).\n\n"
        "  1 = ERROR-severity finding present, OR WARNING count "
        "exceeds --max-warnings.\n\n"
        "  2 = lint-internal error (`error[lint-CODE]:` prefix on stderr) "
        "or click usage error (`Error:` or `Usage:` prefix on stderr)."
    ),
)
@click.argument(
    "inputs",
    nargs=-1,
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--proto",
    "use_proto",
    is_flag=True,
    default=False,
    help="Treat INPUTS as .proto source files (compiled via "
         "protoxy / protoc) instead of pre-built .descriptor_set "
         "files.",
)
@click.option(
    "--proto-path",
    "-I",
    "proto_paths",
    multiple=True,
    metavar="DIR",
    type=click.Path(exists=True, file_okay=False, path_type=str),
    help="Import path for .proto compilation (repeatable). "
         "Only applies with --proto. Analogous to protoc -I. "
         "Must be an existing directory.",
)
@click.option(
    "--rule-pack",
    "rule_packs",
    multiple=True,
    metavar="MODULE",
    help="Fully-qualified Python module path of a user rule pack "
         "(e.g., acme.lint_rules). The module must expose "
         "RULES = (decorated_fn, ...) where each function is "
         "@lint_rule-decorated. Repeatable; loaded on top of the "
         "built-in BUILTIN_PACKS. WARNING: --rule-pack executes "
         "arbitrary Python at import time. Pin --rule-pack values "
         "to vetted sources in CI; do not interpolate from "
         "PR-author-controlled config.",
)
@click.option(
    "--profile",
    "profile_name",
    default="default",
    show_default=True,
    metavar="NAME",
    help="Profile name to resolve across all loaded packs. Each "
         "pack's rules with this profile in their declared "
         "profiles tuple are selected.",
)
@click.option(
    "--min-severity",
    "min_severity",
    type=click.Choice(["info", "warning", "error"], case_sensitive=False),
    default=None,
    help="Override the composed profile's severity floor. Findings "
         "below this severity are filtered. Emits a stderr "
         "advisory line when the override is more lenient than the "
         "composed floor.",
)
@click.option(
    "--format",
    "format_name",
    envvar="PROTOKIT_FORMAT",
    default="human",
    show_default=True,
    show_envvar=True,
    metavar="NAME",
    help="Output format. 'human' is the default and only format "
         "registered in U4a; 'json', 'junit', and 'sarif' arrive "
         "in U4b and currently exit 2 via "
         "error[lint-format-unavailable]:.",
)
@click.option(
    "--max-warnings",
    "max_warnings",
    type=click.IntRange(min=0),
    default=None,
    metavar="N",
    help="CI gate threshold. When set, exit 1 if WARNING-severity "
         "findings (post --min-severity filter) exceed N. "
         "ERROR-severity findings always exit 1 regardless of N. "
         "Omit the flag to skip the WARNING gate entirely (exit 0 "
         "on findings without ERROR). Must be >= 0.",
)
@click.option(
    "--statistics/--no-statistics",
    "statistics",
    default=None,
    help="Append a per-severity finding-count footer to human "
         "output. Default OFF; pass --statistics to opt in. Footer "
         "is human-only — machine formats embed counts in their "
         "structured payloads natively (in U4b). "
         "Zero-count severity rows are suppressed; only non-zero "
         "severities appear below the `statistics:` marker.",
)
@click.option(
    "--quiet",
    "quiet",
    is_flag=True,
    default=False,
    help="Suppress findings on stdout; exit code still reflects "
         "the R20 ladder (0 clean, 1 ERROR or WARNING > "
         "--max-warnings, 2 lint-internal error). Hard mutex with "
         "--format=json/junit/sarif (click usage error). Soft "
         "mutex with --statistics — emits a stderr advisory line "
         "and --quiet wins (no footer).",
)
def main(
    inputs: tuple[Path, ...],
    use_proto: bool,
    proto_paths: tuple[str, ...],
    rule_packs: tuple[str, ...],
    profile_name: str,
    min_severity: str | None,
    format_name: str,
    max_warnings: int | None,
    statistics: bool | None,
    quiet: bool,
) -> None:
    """Lint INPUTS for style and policy violations.

    By default, INPUTS are pre-built ``.descriptor_set`` files
    (``protoc --descriptor_set_out`` output). Pass ``--proto`` to
    treat them as ``.proto`` source files compiled at invocation
    time. Multiple inputs are merged into a single descriptor pool
    with first-occurrence-wins deduplication on ``fd.name``.

    """
    format_name = format_name.lower()
    profile_name = profile_name.lower()
    if quiet and format_name != "human":
        raise click.UsageError(
            f"--quiet is incompatible with --format={format_name!r}; "
            "use --quiet only with the human format (the default)."
        )
    effective_statistics: bool | None = statistics
    if quiet and statistics:
        click.echo(
            "warning[lint-cli]: --quiet suppresses --statistics footer "
            "(--quiet wins)",
            err=True,
        )
        effective_statistics = False
    _main_impl(
        inputs=inputs,
        use_proto=use_proto,
        proto_paths=proto_paths,
        rule_packs=rule_packs,
        profile_name=profile_name,
        min_severity=min_severity,
        format_name=format_name,
        max_warnings=max_warnings,
        statistics=effective_statistics,
        quiet=quiet,
    )


def _main_impl(
    *,
    inputs: tuple[Path, ...],
    use_proto: bool,
    proto_paths: tuple[str, ...],
    rule_packs: tuple[str, ...],
    profile_name: str,
    min_severity: str | None,
    format_name: str,
    max_warnings: int | None,
    statistics: bool | None,
    quiet: bool,
) -> None:
    """Implementation body of ``protokit lint`` after flag validation.

    Auto-loads ``BUILTIN_PACKS`` (the canonical ``naming`` canary
    today). User packs supplied via ``--rule-pack`` load on top.
    See ``BUILTIN_PACKS`` in ``protokit.schema.lint.rules`` for the
    auto-load surface. Each ``--rule-pack`` module must expose
    ``RULES = (decorated_fn, ...)`` where each callable is
    ``@lint_rule``-decorated.
    """
    if use_proto:
        result = compile_protos_to_result(
            paths=list(inputs),
            proto_paths=list(proto_paths),
        )
        # Surface non-error info/warning diagnostics to stderr so
        # protoxy fallback notices and import-resolution warnings
        # don't get silently swallowed (closes U2 ce:review CLR-U2-04
        # / ADV-05 — agents in --proto mode now see all backend
        # diagnostics, not just errors). Error diagnostics are
        # rendered below right before the exit-2 stable-prefix line.
        info_warnings = [d for d in result.diagnostics if d.level != "error"]
        errors = [d for d in result.diagnostics if d.level == "error"]
        for diag in info_warnings:
            click.echo(
                f"{diag.level}[lint-compile]: "
                f"{diag.category}: {diag.message}",
                err=True,
            )
        if errors:
            for diag in errors:
                click.echo(
                    f"diagnostic[{diag.category}]: {diag.message}",
                    err=True,
                )
            error_exit_with_code(
                "compile-failed",
                "source compile produced error-level diagnostics; "
                "see stderr for details.",
            )
    else:
        if proto_paths:
            click.echo(
                "warning[lint-cli]: --proto-path ignored in descriptor-set "
                "mode (only applies with --proto)",
                err=True,
            )
        result = _load_descriptor_sets_to_result(inputs)

    # Build the engine and load BUILTIN_PACKS first, then any user
    # packs supplied via --rule-pack. The order matters because
    # user packs collide on rule_id with built-in packs surface as
    # DuplicateRuleError → error[lint-rule-collision]:.
    engine = LintEngine()
    # Track every successfully-loaded pack (built-ins + user packs)
    # so we can introspect declared profiles for R11 and contributing
    # rule_ids for R25.
    loaded_packs: list[ModuleType] = []
    for pack in BUILTIN_PACKS:
        try:
            engine.load_rule_pack(pack)
        except (DuplicateRuleError, TypeError, AttributeError) as exc:
            error_exit_with_code(
                "rule-pack-load",
                f"kind=builtin: built-in pack {pack.__name__!r} failed "
                f"to load: {_scrub_exc_message(exc)}",
            )
        loaded_packs.append(pack)

    for module_name in rule_packs:
        # Stderr load-banner: every --rule-pack invocation emits
        # an advisory line so the trust delegation is observable.
        # Per the round-1 plan-review P1 finding on --rule-pack
        # security mitigation. Stderr diagnostic; not gated by
        # --quiet (which suppresses findings stdout only).
        safe_module_name = module_name.replace("\n", " ").replace("\r", " ")
        click.echo(
            f"protokit lint: loading user-supplied rule pack "
            f"{safe_module_name!r} (executes arbitrary Python from the "
            f"named module)",
            err=True,
        )
        loaded_packs.append(_load_user_rule_pack(module_name, engine))

    loaded_packs_tuple: tuple[ModuleType, ...] = tuple(loaded_packs)

    # Profile resolution per origin R10 revised: derive each pack's
    # profile via LintProfile.from_pack, then compose if multi-pack.
    # Single-pack short-circuits to the from_pack result (compose's
    # len==1 path returns profiles[0] unchanged anyway, but the
    # explicit branch communicates intent).
    #
    # TODO(next-delivery): when pyproject config introduces non-default
    # min_severity callers (the relaxation-breadcrumb's first real
    # signal), revisit whether the single-pack branch should also go
    # through compose() so the strictest-wins path is exercised
    # uniformly. Today the branch is correct because from_pack always
    # returns min_severity = WARNING; the divergence only matters once
    # callers construct LintProfile with a non-default floor.
    per_pack_profiles: list[LintProfile] = []
    for pack in loaded_packs_tuple:
        try:
            per_pack_profiles.append(LintProfile.from_pack(pack, profile_name))
        except TypeError as exc:
            error_exit_with_code(
                "rule-pack-load",
                f"kind=shape: pack {_safe_module_name(pack)!r} has malformed "
                f"RULES (engine reported: {_scrub_exc_message(exc)})",
            )
    composed_profile = (
        per_pack_profiles[0]
        if len(per_pack_profiles) == 1
        else LintProfile.compose(*per_pack_profiles)
    )

    # Apply --min-severity override (R12). Pure numeric override:
    # replaces the composed profile's min_severity; the
    # LintRuntimeWarning(category="min_severity_relaxed") emission
    # is deferred to the next delivery (pyproject) per origin R12.
    if min_severity is not None:
        override_severity = _MIN_SEVERITY_CHOICES[min_severity.lower()]
        composed_floor = composed_profile.min_severity
        composed_profile = dataclasses.replace(
            composed_profile, min_severity=override_severity,
        )
        # Emit a relaxation breadcrumb when the override is more
        # lenient (lower SEVERITY_RANK = lower severity = more
        # lenient). Stderr diagnostic; not gated by --quiet (which
        # suppresses findings stdout only).
        if (
            SEVERITY_RANK[override_severity]
            < SEVERITY_RANK[composed_floor]
        ):
            click.echo(
                f"protokit lint: --min-severity={min_severity.lower()} "
                f"relaxes profile floor from "
                f"{composed_floor.name.lower()} to "
                f"{override_severity.name.lower()}",
                err=True,
            )

    # Loud-failure checks per origin R9 + R11. R9 wins over R11 when
    # both predicates would fire — the user can't meaningfully fix
    # profile selection without rules to select from.
    if not engine.has_rules:
        error_exit_with_code(
            "no-rules",
            "no lint rules loaded — supply --rule-pack with a pack "
            "exposing RULES, or rely on the built-in BUILTIN_PACKS "
            "(see protokit.schema.lint.rules.BUILTIN_PACKS).",
        )
    if not composed_profile.rule_ids:
        # Emit per-pack introspection as parseable info lines, then the
        # single-line error. Parseable prefix info[lint-pack-profiles]:
        # lets agents extract available profile names without parsing
        # freeform error text.
        declared_per_pack = _declared_profiles_per_pack(loaded_packs_tuple)
        for pack_name, profiles in declared_per_pack.items():
            profiles_str = ", ".join(sorted(profiles)) if profiles else "(none)"
            safe_pack_name = pack_name.replace("\n", " ").replace("\r", " ")
            click.echo(
                f"info[lint-pack-profiles]: pack={safe_pack_name} "
                f"profiles=[{profiles_str}]",
                err=True,
            )
        error_exit_with_code(
            "unknown-profile",
            f"profile {profile_name!r} is not declared by any loaded pack",
        )

    # R25 multi-pack composition stderr provenance line. Gated on
    # len(loaded_packs) >= 2 per origin R25 revised — single-pack
    # default emits no line (it's not composing anything).
    if len(loaded_packs_tuple) >= 2:
        active_per_pack = _active_rule_ids_per_pack(
            loaded_packs_tuple, composed_profile.rule_ids,
        )
        per_pack_segments = [
            f"{_safe_module_name(pack)}=[{','.join(rule_ids)}]"
            for pack, rule_ids in zip(
                loaded_packs_tuple, active_per_pack.values(), strict=True,
            )
        ]
        click.echo(
            f"protokit lint: profile {profile_name!r} from "
            + "; ".join(per_pack_segments),
            err=True,
        )

    report = engine.run(result, profile=composed_profile)

    # Emit runtime warnings to stderr (closes U2 ce:review CLR-U2-03
    # / agent-native warning #5). Two categories surface here:
    # `rule_exception` (a rule callable raised an exception caught
    # by the engine's narrow catch tuple) and `unloaded_rule` (the
    # active profile names a rule_id not loaded into the engine —
    # reachable now that --rule-pack ships). Stderr diagnostic; not
    # gated by --quiet (which suppresses findings stdout only).
    for warning in report.runtime_warnings:
        safe_message = warning.message.replace("\n", " ").replace("\r", " ")
        click.echo(
            f"warning[lint-runtime]: {warning.category}: {safe_message}",
            err=True,
        )

    try:
        formatter = get_formatter(format_name, FormatterKind.LINT_REPORT)
    except KeyError:
        available = ", ".join(sorted(list_formatters(FormatterKind.LINT_REPORT)))
        error_exit_with_code(
            "format-unavailable",
            f"unknown format {format_name!r} for lint output "
            f"(available: {available})",
        )

    ctx = FormatterContext(subcommand="lint")
    output = _run_lint_formatter_safely(
        formatter, report, ctx, name=format_name,
    )
    if output and not quiet:
        click.echo(output)

    if statistics and format_name == "human" and not quiet:
        _emit_statistics_footer(report)

    has_error = any(
        finding.severity is LintSeverity.ERROR
        for finding in report.findings
    )
    if has_error:
        sys.exit(1)
    if max_warnings is not None:
        warning_count = sum(
            1 for finding in report.findings
            if finding.severity is LintSeverity.WARNING
        )
        if warning_count > max_warnings:
            sys.exit(1)


def _emit_statistics_footer(report: LintReport) -> None:
    """Emit a per-severity finding-count footer to stdout.

    Empty rows (zero counts) are suppressed; the footer marker line
    always emits when --statistics is set. Agents can verify the flag
    was honored by checking for the `statistics:` marker line, but
    should not parse individual rows as a stable contract — machine-readable
    counts arrive in U4b's structured formats.
    """
    counts: Counter[LintSeverity] = Counter(
        finding.severity for finding in report.findings
    )

    click.echo("statistics:")
    if counts[LintSeverity.ERROR]:
        click.echo(f"  errors: {counts[LintSeverity.ERROR]}")
    if counts[LintSeverity.WARNING]:
        click.echo(f"  warnings: {counts[LintSeverity.WARNING]}")
    if counts[LintSeverity.INFO]:
        click.echo(f"  info: {counts[LintSeverity.INFO]}")
    if report.filtered_count:
        click.echo(f"  filtered: {report.filtered_count}")
    if report.runtime_warnings:
        click.echo(f"  runtime-warnings: {len(report.runtime_warnings)}")
