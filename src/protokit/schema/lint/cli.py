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
       severity floor. When the override is more lenient than the
       composed floor, a structured ``min_severity_relaxed`` runtime
       warning is emitted in ``report.runtime_warnings`` (D5 U4
       replaces the U3 stderr breadcrumb with structured emission).
    4. R9 zero-rules loud failure (``error[lint-no-rules]:``).
    5. R11 unknown-profile loud failure (``error[lint-unknown-profile]:``)
       with per-pack introspection of declared profile names.
    6. R25 multi-pack composition stderr provenance line — gated on
       ``len(loaded_packs) >= 2`` (single-pack default emits no line
       per origin R25 revised).
    7. Runtime-warning emission — engine warnings (``rule_exception``,
       ``unloaded_rule``) are captured in ``report.runtime_warnings``
       and rendered by formatter dispatch. D5 U4 removed the
       ``warning[lint-runtime]:`` stderr loop; warnings now surface
       via the machine formatters (``--format=json`` /
       ``--format=junit`` / ``--format=sarif``). D5 U5 adds a
       post-format hook so ``--format=human`` re-emits to stderr.
    8. Non-error compile diagnostics in ``--proto`` mode — info /
       warning level diagnostics from the protoxy/protoc backend
       surface to stderr alongside (or instead of) the
       ``compile-failed`` exit path.

U4a wires the R20 exit-code ladder + ``--max-warnings`` /
``--statistics`` / ``--quiet`` / ``--format``. U4b adds the three
machine formatters.
"""

from __future__ import annotations

import dataclasses
import sys
from collections import Counter
from pathlib import Path
from types import ModuleType
from typing import Any

import click
from click.core import ParameterSource as _ParameterSource

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
    _safe_for_stderr,
    _safe_module_name,
    error_exit_with_code,
)
from protokit.schema.lint._config import (
    ResolvedLintConfig,
    compile_exclude_patterns,
    load_pyproject_config,
)
from protokit.schema.lint.engine import LintEngine
from protokit.schema.lint.model import (
    DuplicateRuleError,
    LintProfile,
    LintReport,
    LintRuntimeWarning,
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

#: Per-category emit budget for the ``--format=human`` runtime-warning
#: stderr hook (D5 U5 R21a). Once a category exceeds this count, the
#: hook collapses the remainder into a single summarization line and
#: stops emitting individual warnings for that category. Machine
#: formatters (``json`` / ``junit`` / ``sarif``) always emit ALL
#: warnings unconditionally — summarization is human-only per
#: KTD-6.
#:
#: Tests pin behaviour against ``threshold`` / ``threshold + 1``
#: boundaries via ``monkeypatch.setattr`` rather than the literal
#: value, so D6+ tuning does not require coordinated test updates.
_LINT_HUMAN_SUMMARIZATION_THRESHOLD: int = 5


def _emit_human_runtime_warnings(report: LintReport) -> None:
    """Emit ``report.runtime_warnings`` to stderr as human-format lines.

    Called only when ``resolved.format == "human"`` (the CLI-side
    post-format hook per KTD-6). Each warning becomes a stderr line
    of the form::

        protokit lint: warning [{category}]: {message}

    Per-category counters track how many lines fired; once a
    category's count exceeds ``_LINT_HUMAN_SUMMARIZATION_THRESHOLD``,
    a single summarization line replaces the remaining individuals
    for that category::

        protokit lint: warning [{category}]: ... and {N} more
        — use --format=json for full details

    Both the ``{category}`` and ``{message}`` slots are passed
    through ``_safe_for_stderr`` before ``click.echo`` as a
    defense-in-depth measure (per KTD-9): construction-time
    sanitization in engine.py / cli.py already collapses control
    characters in the message field, and the ``category`` field is
    typed as a closed ``Literal[...]`` set whose four values are all
    ASCII tokens — but Python does not enforce ``Literal`` at
    runtime, so a future emission site that constructs a
    ``LintRuntimeWarning`` with a control-character-bearing category
    string would otherwise bypass the boundary. Sanitizing both
    slots keeps the stderr boundary symmetric and immune to that
    future-emission-site regression.

    A non-positive ``_LINT_HUMAN_SUMMARIZATION_THRESHOLD`` is
    clamped to ``1`` at function entry so the summarization math
    stays well-defined under accidental D6 tuning to ``0`` or
    negative values (zero would fire summary on the first warning
    with "and N more" framing implying prior emissions; negative
    would overcount remaining by ``abs(threshold)``).

    This hook is **NOT** gated by ``--quiet`` (KTD-6): ``--quiet``
    suppresses findings on stdout, not warnings on stderr. The
    pre-U4 stderr breadcrumb had the same posture (an inline
    comment on the deleted ``cli.py:498-503`` loop said as much).
    Closes the D3-era silent-warning regression for
    ``--format=human``.
    """
    if not report.runtime_warnings:
        return
    threshold = max(1, _LINT_HUMAN_SUMMARIZATION_THRESHOLD)
    per_category_total: Counter[str] = Counter(
        w.category for w in report.runtime_warnings
    )
    per_category_emitted: Counter[str] = Counter()
    for w in report.runtime_warnings:
        per_category_emitted[w.category] += 1
        safe_category = _safe_for_stderr(w.category)
        if per_category_emitted[w.category] <= threshold:
            safe_message = _safe_for_stderr(w.message)
            click.echo(
                f"protokit lint: warning [{safe_category}]: {safe_message}",
                err=True,
            )
        elif per_category_emitted[w.category] == threshold + 1:
            # First overflow for this category — emit the
            # summarization line exactly once. Subsequent overflow
            # warnings for the same category fall through silently
            # because their emit count exceeds ``threshold + 1`` and
            # neither branch matches. The numeric equality replaces
            # an earlier ``summarized: set[str]`` guard that tracked
            # the same first-overflow membership less directly.
            remaining = per_category_total[w.category] - threshold
            click.echo(
                f"protokit lint: warning [{safe_category}]: ... and "
                f"{remaining} more — use --format=json for full details",
                err=True,
            )


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
        "  Use project-specific config from pyproject.toml:\n\n"
        "    protokit lint --config ./pyproject.toml schema.descriptor_set\n\n"
        "  Use a multi-profile composition (pyproject only — single "
        "value via CLI):\n\n"
        "    # pyproject.toml: [tool.protokit.lint]\n\n"
        "    #                  profile = [\"default\", \"strict-naming\"]\n\n"
        "    protokit lint schema.descriptor_set\n\n"
        "  Exclude files matching gitignore-style patterns "
        "(repeatable):\n\n"
        "    protokit lint --exclude 'vendor/**' "
        "--exclude '!vendor/critical.proto' schema.descriptor_set\n\n"
        "  Bypass any pyproject `[tool.protokit.lint] exclude` "
        "(lint all files):\n\n"
        "    protokit lint --no-exclude schema.descriptor_set\n\n"
        "  Bypass pyproject discovery (containerized CI without "
        ".git boundary):\n\n"
        "    protokit lint --no-config schema.descriptor_set\n\n"
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
    help=(
        "Profile name to resolve across all loaded packs. Each pack's "
        "rules with this profile in their declared profiles tuple are "
        "selected. When --profile is not explicitly passed, "
        "`[tool.protokit.lint] profile` in pyproject.toml is used if "
        "present (scalar string or list of strings for multi-profile "
        "composition). Explicitly passing this flag — including "
        "`--profile default` — overrides any pyproject profile value."
    ),
)
@click.option(
    "--min-severity",
    "min_severity",
    type=click.Choice(["info", "warning", "error"], case_sensitive=False),
    default=None,
    help="Override the composed profile's severity floor. Findings "
         "below this severity are filtered. When the override is "
         "more lenient than the composed profile floor, a structured "
         "min_severity_relaxed runtime warning is emitted in "
         "report.runtime_warnings. Under --format=human (default) "
         "the warning also surfaces on stderr as "
         "'protokit lint: warning [min_severity_relaxed]: ...'; use "
         "--format=json for full machine-readable access.",
)
@click.option(
    "--format",
    "format_name",
    envvar="PROTOKIT_FORMAT",
    default="human",
    show_default=True,
    show_envvar=True,
    metavar="NAME",
    help=(
        "Output format. One of: 'human' (default — findings on "
        "stdout; runtime warnings on stderr as "
        "'protokit lint: warning [<category>]: ...' lines), "
        "'json' (structured JSON on stdout with a runtime_warnings "
        "array), 'junit' (JUnit XML; runtime warnings appear in the "
        "testsuite <system-out>), 'sarif' (SARIF 2.1.0 with runtime "
        "warnings in runs[].properties.runtime_warnings). Use "
        "--format=json for full machine-readable access to all "
        "runtime warnings (human format may summarize per-category "
        "above an internal threshold). Precedence: CLI --format > "
        "PROTOKIT_FORMAT envvar > [tool.protokit.lint] format in "
        "pyproject.toml > built-in default ('human'). Envvar and CLI "
        "flag are treated as explicit and override pyproject."
    ),
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
         "and --quiet wins (no footer). Runtime-warning stderr lines "
         "emitted under --format=human (default) are NOT suppressed "
         "by --quiet — only stdout findings are; use --format=json "
         "to route warnings into structured stdout instead of stderr.",
)
@click.option(
    "--config",
    "config_path",
    default=None,
    metavar="PATH",
    type=click.Path(path_type=Path),
    # Fix #2: expand `~` to the home directory at the Click input
    # boundary (per the normalize-at-input-boundary-2026-05-07
    # learning). Without this, `--config ~/config.toml` would fail
    # with "does not exist" because Click's Path() does not expand
    # tildes itself.
    callback=lambda ctx, param, value: (
        value.expanduser() if value is not None else value
    ),
    # Existence + readability + format checks are performed by
    # protokit.schema.lint._config.load_pyproject_config so they
    # produce the error[lint-pyproject-config-load]: stable prefix
    # rather than click's default 'Usage:' prefix. Do NOT pass
    # exists=True here.
    help="Path to a pyproject.toml-style file to load "
         "[tool.protokit.lint] from. Overrides walk-up discovery. "
         "If the file is missing, unreadable, or has no "
         "[tool.protokit.lint] table, exits 2 with "
         "error[lint-pyproject-config-load]:. Mutually exclusive "
         "with --no-config. When given multiple times, the last "
         "value wins.",
)
@click.option(
    "--no-config",
    "no_config",
    is_flag=True,
    default=False,
    help="Bypass pyproject.toml discovery entirely; run with "
         "built-in defaults only. Mutually exclusive with --config. "
         "Useful for verifying CI runs with intended defaults, or "
         "in environments without a .git boundary where walk-up "
         "may otherwise consume an unintended parent pyproject.",
)
@click.option(
    "--exclude",
    "exclude_patterns",
    multiple=True,
    metavar="PATTERN",
    help="Gitignore-style glob pattern to exclude files from the "
         "lint pass (repeatable). Matched against "
         "FileDescriptorProto.name (i.e., the path the file was "
         "registered under). When --exclude is not explicitly passed, "
         "`[tool.protokit.lint] exclude` in pyproject.toml is used "
         "if present (list of patterns). CLI patterns APPEND to "
         "pyproject patterns; see --no-exclude to clear both. "
         "Patterns use gitignore-style semantics including negation: "
         "`--exclude 'vendor/**' --exclude '!vendor/important.proto'` "
         "excludes everything under vendor/ except the named file. "
         "The descriptor pool still loads all files (per R9: "
         "filtering applies to findings emission, not pool loading); "
         "an --exclude'd file's symbols remain resolvable as "
         "transitive imports for other files.",
)
@click.option(
    "--no-exclude",
    "no_exclude",
    is_flag=True,
    default=False,
    help="Bypass all exclude patterns (CLI --exclude AND pyproject "
         "[tool.protokit.lint] exclude). When --no-exclude is set, "
         "every input file is linted regardless of pattern matches. "
         "Useful for verifying that a pyproject exclude list is the "
         "reason an expected finding is not surfacing, or in CI "
         "configurations that override the project's default "
         "exclude policy.",
)
@click.pass_context
def main(
    ctx: click.Context,
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
    config_path: Path | None,
    no_config: bool,
    exclude_patterns: tuple[str, ...],
    no_exclude: bool,
) -> None:
    """Lint INPUTS for style and policy violations.

    By default, INPUTS are pre-built ``.descriptor_set`` files
    (``protoc --descriptor_set_out`` output). Pass ``--proto`` to
    treat them as ``.proto`` source files compiled at invocation
    time. Multiple inputs are merged into a single descriptor pool
    with first-occurrence-wins deduplication on ``fd.name``.

    """
    # D5 R5a + R13a-precedence: --config and --no-config are mutually
    # exclusive. Click-level mutex emits the 'Usage:' prefix and exits
    # 2 — distinct from --config's loader-side R5a errors which carry
    # the error[lint-pyproject-config-load]: prefix.
    if config_path is not None and no_config:
        raise click.UsageError(
            "--config and --no-config are mutually exclusive; pass one or "
            "neither.",
        )
    effective_statistics: bool | None = statistics
    if quiet and statistics:
        click.echo(
            "warning[lint-cli]: --quiet suppresses --statistics footer "
            "(--quiet wins)",
            err=True,
        )
        effective_statistics = False
    # D5 U3: --no-exclude wins over --exclude per KTD-10. When both are
    # supplied, drop the --exclude patterns silently after announcing
    # the override on stderr (mirrors the --quiet/--statistics
    # soft-mutex pattern above).
    if no_exclude and exclude_patterns:
        click.echo(
            "warning[lint-cli]: --no-exclude clears --exclude patterns "
            "(--no-exclude wins)",
            err=True,
        )
    # D5 U1: load [tool.protokit.lint] from pyproject.toml.
    # If load_pyproject_config raises SystemExit (any R5a shadow path,
    # parse error), it never returns and the CLI exits 2 with the
    # error[lint-pyproject-config-load]: stable prefix.
    pyproject_config = load_pyproject_config(
        explicit_path=config_path,
        no_config=no_config,
    )
    # D5 U2: validate the pyproject table (R3, R3a/KTD-5) and merge with
    # CLI overrides into a single ResolvedLintConfig carrier. CLI-default
    # values for --profile and --format are indistinguishable from
    # explicit user choices by value alone (defaults: "default" and
    # "human"), so we rely on Click's parameter-source detection to know
    # whether the user actually typed the flag. COMMANDLINE, ENVIRONMENT,
    # and DEFAULT_MAP all count as "explicit" — env vars like
    # PROTOKIT_FORMAT are first-class user intent, and programmatic
    # callers using ``click.Context(default_map=...)`` are similarly
    # asserting user-level override intent (e.g., embedding the CLI in
    # a test harness or wrapper that injects overrides). DEFAULT means
    # only the click flag's built-in default applied, in which case
    # pyproject (then built-in defaults) take precedence.
    explicit_sources = (
        _ParameterSource.COMMANDLINE,
        _ParameterSource.ENVIRONMENT,
        _ParameterSource.DEFAULT_MAP,
    )
    profile_explicit = (
        ctx.get_parameter_source("profile_name") in explicit_sources
    )
    format_explicit = (
        ctx.get_parameter_source("format_name") in explicit_sources
    )
    # D5 U3: --exclude / --no-exclude → cli_overrides["exclude"]. See
    # ResolvedLintConfig.from_dict's docstring for the full
    # None/()/non-empty sentinel contract. Local note: click's
    # `multiple=True` default-empty-tuple is indistinguishable from
    # "user passed --exclude ''" by value alone, so the explicit
    # `no_exclude` boolean disambiguates "--no-exclude clear-all"
    # from "no --exclude flag passed."
    cli_exclude_value: tuple[str, ...] | None
    if no_exclude:
        cli_exclude_value = ()
    elif exclude_patterns:
        cli_exclude_value = exclude_patterns
    else:
        cli_exclude_value = None
    cli_overrides: dict[str, Any] = {
        "profile": (
            (profile_name.strip().lower(),) if profile_explicit else None
        ),
        "min_severity": (
            _MIN_SEVERITY_CHOICES[min_severity.lower()]
            if min_severity is not None
            else None
        ),
        "max_warnings": max_warnings,
        "format": (
            format_name.strip().lower() if format_explicit else None
        ),
        "exclude": cli_exclude_value,
    }
    resolved = ResolvedLintConfig.from_dict(pyproject_config, cli_overrides)
    # quiet + non-human-format mutex applies to the RESOLVED format so
    # pyproject-driven non-human formats are caught alongside CLI-driven
    # ones. Moved AFTER from_dict for that reason. The error message is
    # source-aware so users see the actual flag/key name that set the
    # offending format — `--format=X` for CLI (or PROTOKIT_FORMAT envvar)
    # source, `[tool.protokit.lint] format=X` for pyproject source.
    if quiet and resolved.format != "human":
        if format_explicit:
            source_desc = f"--format={resolved.format!r}"
        else:
            source_desc = (
                f"[tool.protokit.lint] format={resolved.format!r}"
            )
        raise click.UsageError(
            f"--quiet is incompatible with {source_desc}; "
            "use --quiet only with the human format (the default).",
        )
    _main_impl(
        inputs=inputs,
        use_proto=use_proto,
        proto_paths=proto_paths,
        rule_packs=rule_packs,
        statistics=effective_statistics,
        quiet=quiet,
        resolved=resolved,
    )


def _main_impl(
    *,
    inputs: tuple[Path, ...],
    use_proto: bool,
    proto_paths: tuple[str, ...],
    rule_packs: tuple[str, ...],
    statistics: bool | None,
    quiet: bool,
    resolved: ResolvedLintConfig,
) -> None:
    """Implementation body of ``protokit lint`` after flag validation.

    Auto-loads ``BUILTIN_PACKS`` (the canonical ``naming`` canary
    today). User packs supplied via ``--rule-pack`` load on top.
    See ``BUILTIN_PACKS`` in ``protokit.schema.lint.rules`` for the
    auto-load surface. Each ``--rule-pack`` module must expose
    ``RULES = (decorated_fn, ...)`` where each callable is
    ``@lint_rule``-decorated.

    ``resolved`` (D5 U2) is a ``ResolvedLintConfig`` carrier: the
    merged result of CLI flags + pyproject ``[tool.protokit.lint]`` +
    built-in defaults, with per-key precedence already applied per
    the plan's decision matrix. Consumers in this function:

    - ``resolved.profile`` — iterated to compose multi-profile
      pyproject configurations (single-profile is the common case).
    - ``resolved.min_severity`` + ``resolved.min_severity_source`` —
      drives the relaxation breadcrumb (U4 replaces this with the
      structured ``LintRuntimeWarning`` emission).
    - ``resolved.max_warnings``, ``resolved.format`` — replace the
      former CLI-flag-direct usage.
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
        # ``_safe_for_stderr`` (the project-wide sanitizer) covers the
        # full ASCII control range plus Unicode line terminators
        # U+0085/U+2028/U+2029. The earlier chained ``.replace()``
        # form only handled ``\n``/``\r`` and was bypassed by Unicode
        # line terminators that log aggregators split records on.
        # See docs/solutions/security-issues/
        # module-name-newline-injection-stderr-forge-2026-05-07.md.
        safe_module_name = _safe_for_stderr(module_name)
        click.echo(
            f"protokit lint: loading user-supplied rule pack "
            f"{safe_module_name!r} (executes arbitrary Python from the "
            f"named module)",
            err=True,
        )
        loaded_packs.append(_load_user_rule_pack(module_name, engine))

    loaded_packs_tuple: tuple[ModuleType, ...] = tuple(loaded_packs)

    # Profile resolution: iterate resolved.profile (one name per
    # pyproject `profile = "..."` scalar, or one name per element of
    # `profile = [...]` list). For each name, query each loaded pack;
    # compose pack-side per name; then compose across names.
    # Single-profile-single-pack short-circuits to the from_pack result.
    profiles_per_name: list[LintProfile] = []
    for resolved_profile_name in resolved.profile:
        per_pack_profiles: list[LintProfile] = []
        for pack in loaded_packs_tuple:
            try:
                per_pack_profiles.append(
                    LintProfile.from_pack(pack, resolved_profile_name),
                )
            except TypeError as exc:
                error_exit_with_code(
                    "rule-pack-load",
                    f"kind=shape: pack {_safe_module_name(pack)!r} has "
                    f"malformed RULES (engine reported: "
                    f"{_scrub_exc_message(exc)})",
                )
        composed_for_name = (
            per_pack_profiles[0]
            if len(per_pack_profiles) == 1
            else LintProfile.compose(*per_pack_profiles)
        )
        profiles_per_name.append(composed_for_name)
    composed_profile = (
        profiles_per_name[0]
        if len(profiles_per_name) == 1
        else LintProfile.compose(*profiles_per_name)
    )

    # Apply min_severity override (R12, R19a). Pure numeric override
    # that replaces the composed profile's min_severity. The R20
    # relaxation message (if the override actually relaxes the floor)
    # is computed HERE and emitted post-engine.run as a structured
    # LintRuntimeWarning(category="min_severity_relaxed") per KTD-6 +
    # R19a. The U2 stderr breadcrumb was removed in D5 U4 in favor of
    # this structured emission; the R20 message templates now live on
    # ResolvedLintConfig.relaxation_message per the
    # cross-format-enum-string-parity learning so every formatter
    # emits identical text.
    relaxation_msg: str | None = None
    if resolved.min_severity is not None:
        composed_floor = composed_profile.min_severity
        composed_profile = dataclasses.replace(
            composed_profile, min_severity=resolved.min_severity,
        )
        # relaxation_message returns None when no relaxation actually
        # occurred (resolved >= floor) — the override may equal or
        # exceed the floor, in which case no warning fires.
        relaxation_msg = resolved.relaxation_message(composed_floor)

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
            # Use the project-wide ``_safe_for_stderr`` sanitizer
            # rather than chained ``.replace()`` so Unicode line
            # terminators are covered alongside ``\n``/``\r``. See
            # docs/solutions/security-issues/
            # module-name-newline-injection-stderr-forge-2026-05-07.md.
            safe_pack_name = _safe_for_stderr(pack_name)
            click.echo(
                f"info[lint-pack-profiles]: pack={safe_pack_name} "
                f"profiles=[{profiles_str}]",
                err=True,
            )
        # Multi-profile error names each profile; single-profile keeps
        # the original singular form for back-compat with existing tests
        # and CI grep contracts.
        if len(resolved.profile) == 1:
            error_exit_with_code(
                "unknown-profile",
                f"profile {resolved.profile[0]!r} is not declared by "
                f"any loaded pack",
            )
        profile_list = ", ".join(repr(name) for name in resolved.profile)
        error_exit_with_code(
            "unknown-profile",
            f"profiles {profile_list} are not declared by any loaded pack",
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
        # Render multi-profile as "default+strict-naming" for the
        # provenance line so the resolved set is observable.
        provenance_profile = (
            resolved.profile[0]
            if len(resolved.profile) == 1
            else "+".join(resolved.profile)
        )
        click.echo(
            f"protokit lint: profile {provenance_profile!r} from "
            + "; ".join(per_pack_segments),
            err=True,
        )

    # D5 U3: file-level exclusion. Apply `resolved.exclude` patterns to
    # the post-compile `result.root_files` BEFORE invoking the engine.
    # Per R9, the descriptor POOL still loads every file (so transitive
    # imports resolve), but the engine only walks files that survive
    # the filter. When zero files survive AND the user passed inputs
    # at all, emit `LintRuntimeWarning(category="all_files_excluded")`
    # CLI-side per KTD-4 + KTD-6 and short-circuit `engine.run` with
    # an empty report; downstream rendering still fires so the
    # warning surfaces in every formatter.
    all_files_excluded_warning: LintRuntimeWarning | None = None
    if resolved.exclude:
        exclude_spec = compile_exclude_patterns(resolved.exclude)
        filtered_root_files = tuple(
            f for f in result.root_files
            if not exclude_spec.match_file(f)
        )
        if (
            len(filtered_root_files) == 0
            and len(result.root_files) > 0
        ):
            # D5 U4 F-03 fold-in: the all_files_excluded message is
            # now R20-source-attributed via
            # ResolvedLintConfig.all_files_excluded_message, so users
            # see whether the dropping patterns came from --exclude,
            # pyproject, or both. Per KTD-9, patterns are
            # newline-sanitized inside the helper.
            all_files_excluded_warning = LintRuntimeWarning(
                category="all_files_excluded",
                rule_id=None,
                message=resolved.all_files_excluded_message(
                    len(result.root_files),
                ),
            )
        else:
            result = dataclasses.replace(
                result, root_files=filtered_root_files,
            )

    if all_files_excluded_warning is not None:
        # Short-circuit: skip engine.run and emit an empty report
        # whose runtime_warnings carries the all_files_excluded
        # CLI-side warning. Downstream rendering (formatter dispatch)
        # still runs so the warning surfaces in every output format.
        report = LintReport(
            findings=(),
            diagnostics=result.diagnostics,
            profiles_run=(composed_profile.name,),
            rules_run=tuple(sorted(composed_profile.rule_ids)),
            runtime_warnings=(all_files_excluded_warning,),
        )
    else:
        report = engine.run(result, profile=composed_profile)

    # D5 U4 R19a: post-engine append for `min_severity_relaxed`. Per
    # KTD-4 alphabetical ordering, this comes AFTER any
    # `all_files_excluded` already attached above
    # (alphabetical: all_files_excluded < min_severity_relaxed).
    # Engine-emitted categories (`rule_exception`, `unloaded_rule`)
    # come first by emission order; CLI-emitted categories are
    # appended in alphabetical sequence here.
    if relaxation_msg is not None:
        relaxation_warning = LintRuntimeWarning(
            category="min_severity_relaxed",
            rule_id=None,
            message=relaxation_msg,
        )
        report = dataclasses.replace(
            report,
            runtime_warnings=(
                report.runtime_warnings + (relaxation_warning,)
            ),
        )

    try:
        formatter = get_formatter(resolved.format, FormatterKind.LINT_REPORT)
    except KeyError:
        available = ", ".join(sorted(list_formatters(FormatterKind.LINT_REPORT)))
        error_exit_with_code(
            "format-unavailable",
            f"unknown format {resolved.format!r} for lint output "
            f"(available: {available})",
        )

    fmt_ctx = FormatterContext(subcommand="lint")
    output = _run_lint_formatter_safely(
        formatter, report, fmt_ctx, name=resolved.format,
    )
    if output and not quiet:
        click.echo(output)

    # D5 U5 R21a: CLI-side post-format hook for ``--format=human``.
    # The machine formatters (``lint_json`` / ``lint_junit`` /
    # ``lint_sarif``) embed ``runtime_warnings`` in their structured
    # payloads; ``lint_human`` is intentionally pure (returns the
    # findings string), so re-surfacing the warnings to stderr is
    # CLI-layer policy per KTD-6. The hook is NOT gated by
    # ``--quiet`` (warnings on stderr stay visible; ``--quiet``
    # suppresses findings on stdout).
    if resolved.format == "human":
        _emit_human_runtime_warnings(report)

    if statistics and resolved.format == "human" and not quiet:
        _emit_statistics_footer(report)

    has_error = any(
        finding.severity is LintSeverity.ERROR
        for finding in report.findings
    )
    if has_error:
        sys.exit(1)
    if resolved.max_warnings is not None:
        warning_count = sum(
            1 for finding in report.findings
            if finding.severity is LintSeverity.WARNING
        )
        if warning_count > resolved.max_warnings:
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
