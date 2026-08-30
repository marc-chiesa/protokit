"""``protokit lint`` click subcommand.

Single-command click subcommand (NOT a sub-group). Registered on
the top-level ``protokit`` CLI group at ``src/protokit/cli.py``.

This module imports ``protokit.formatters._builtin_lint`` at module
top, which triggers the side-effect registration of the four lint
formatters (``lint_human``, ``lint_json``, ``lint_junit``,
``lint_sarif``). Registration runs at ``protokit.cli`` load time —
i.e., on every ``protokit ...`` invocation, regardless of which
subcommand the user fires.

Cold-import contract: ``import protokit.schema`` does NOT
transitively load this module. The contract is preserved by NOT
adding ``_builtin_lint`` to ``formatters/__init__.py``'s eager-load
tuple.

Pipeline overview:
    1. ``--rule-pack MODULE`` (repeatable) — load user-supplied rule
       packs on top of BUILTIN_PACKS via ``importlib.import_module``.
    2. ``--profile NAME`` (default ``"default"``) — select which
       profile each pack contributes to the resolved set.
    3. ``--min-severity LEVEL`` — override the composed profile's
       severity floor. When the override is more lenient than the
       composed floor, a structured ``min_severity_relaxed`` runtime
       warning is emitted in ``report.runtime_warnings``.
    4. Zero-rules loud failure (``error[lint-no-rules]:``).
    5. Unknown-profile loud failure (``error[lint-unknown-profile]:``)
       with per-pack introspection of declared profile names.
    6. Multi-pack composition stderr provenance line — gated on
       ``len(loaded_packs) >= 2`` (single-pack default emits no line).
    7. Runtime-warning emission — engine warnings (``rule_exception``,
       ``unloaded_rule``) are captured in ``report.runtime_warnings``
       and rendered by formatter dispatch. Warnings surface via the
       machine formatters (``--format=json`` / ``--format=junit`` /
       ``--format=sarif``); a post-format hook re-emits them to
       stderr for ``--format=human``.
    8. Non-error compile diagnostics in ``--proto`` mode — info /
       warning level diagnostics from the protoxy/protoc backend
       surface to stderr alongside (or instead of) the
       ``compile-failed`` exit path.

The exit-code ladder, ``--max-warnings``, ``--statistics``,
``--quiet``, and ``--format`` are all wired through the resolved
config carrier; see ``ResolvedLintConfig`` for the precedence rules.
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
from protokit.schema.lint._custom_rules import (
    build_synthetic_module,
    synthetic_rule_ids,
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
#: stderr hook. Once a category exceeds this count, the hook collapses
#: the remainder into a single summarization line and stops emitting
#: individual warnings for that category. Machine formatters
#: (``json`` / ``junit`` / ``sarif``) always emit ALL warnings
#: unconditionally — summarization is human-only.
#:
#: Tests pin behaviour against ``threshold`` / ``threshold + 1``
#: boundaries via ``monkeypatch.setattr`` rather than the literal
#: value, so future tuning does not require coordinated test updates.
_LINT_HUMAN_SUMMARIZATION_THRESHOLD: int = 5

#: Pinned buf version for the parity CI job and ``tests/parity/``.
#: This constant and the corresponding
#: ``releases/download/v<X>/buf-Linux-x86_64.tar.gz`` URL in
#: ``.github/workflows/ci.yml``'s parity job MUST reference the same
#: version. Drift between the two is caught by
#: ``tests/meta/test_buf_parity_pin_drift.py`` in the default
#: ``pytest tests/`` invocation, so a contributor bumping one
#: without the other fails locally before push.
#:
#: The release watcher at ``.github/workflows/buf-release-watch.yml``
#: greps this line weekly and opens a tracking issue when upstream
#: ships a newer stable release. Pin bumps are deliberate acts —
#: the watcher surfaces the signal; a maintainer lands the bump as
#: a discrete PR after fixture / parity-test review.
#:
#: This constant is also wired into ``protokit lint --version``
#: output via ``_print_lint_version`` below so users can verify the
#: parity reference without reading CI YAML. CONTRIBUTING.md points
#: readers here as the canonical source for the pinned buf version.
_BUF_PARITY_PIN: str = "v1.70.0"

#: ``LintRuntimeWarning`` categories that mean a rule did not run, and
#: therefore that the report is a lower bound on an unknown total
#: rather than a complete answer. Membership here drives the
#: ``analysis-incomplete`` exit-2 gate (V33).
#:
#: Deliberately narrow, and KNOWN INCOMPLETE. Three further categories
#: also mean a rule did not run, and this gate does not fire for them:
#: ``extension_unresolved`` and ``custom_annotation_extension_unresolved``
#: (``model.py`` says each "skips without firing findings"), and
#: ``all_files_excluded`` (the engine is short-circuited entirely — the
#: lint equivalent of V31). They are excluded here for blast radius, not
#: because they are sound: ``extension_unresolved`` fires on essentially
#: every run whose inputs lack ``google/api/field_behavior.proto``, so
#: gating it would exit 2 almost everywhere, and the honest fix is to
#: make that rule warn only when the schema actually *uses* the
#: extension. That is a redesign, not a patch. **U7/U8 own all three**;
#: the triage ledger records the reproductions. The remaining
#: categories (``severities_unloaded_rule``, ``min_severity_relaxed``,
#: ``contradictory_disable_config``, ``unknown_rule_id``) are genuinely
#: advisory: they describe ineffective overrides or nonexistent ids,
#: not a selected rule that failed to execute.
_INCOMPLETE_ANALYSIS_CATEGORIES: tuple[str, ...] = (
    "rule_exception",
    "unloaded_rule",
)


def _print_lint_version(
    ctx: click.Context, _param: click.Parameter, value: bool,
) -> None:
    """Eager callback for ``protokit lint --version``.

    Prints ``protokit X.Y.Z (parity: buf v<PIN>)`` and exits before
    any other CLI option is parsed. The top-level
    ``protokit --version`` (via ``@click.version_option`` at
    ``src/protokit/cli.py:24``) outputs only the package version;
    this callback extends the lint subcommand with the buf-parity
    pin surface so users can verify the parity reference without
    reading CI YAML.

    Implementation: standard Click eager-flag callback shape — if
    ``value`` is False (flag not set) or the resilient parsing pass
    is in progress, return immediately. Otherwise echo the version
    line and call ``ctx.exit(0)`` so the rest of the lint pipeline
    is skipped (just like Click's built-in ``version_option``).

    **Output format stability**: the line shape
    ``protokit <ver> (parity: buf <pin>)`` is a public contract.
    Agents grep ``parity: buf v\\S+`` to extract the pin. Additional
    tokens (e.g., ``protoc v...``) MUST append within the existing
    parenthetical and require a minor-version bump. The literal
    string ``"parity: buf "`` is a load-bearing anchor.
    """
    if not value or ctx.resilient_parsing:
        return
    from protokit._cli_utils import _get_protokit_version
    click.echo(
        f"protokit {_get_protokit_version()} (parity: buf {_BUF_PARITY_PIN})"
    )
    ctx.exit(0)


def _emit_human_runtime_warnings(report: LintReport) -> None:
    """Emit ``report.runtime_warnings`` to stderr as human-format lines.

    Called only when ``resolved.format == "human"`` (the CLI-side
    post-format hook). Each warning becomes a stderr line of the form::

        protokit lint: warning [{category}]: {message}

    Per-category counters track how many lines fired; once a
    category's count exceeds ``_LINT_HUMAN_SUMMARIZATION_THRESHOLD``,
    a single summarization line replaces the remaining individuals
    for that category. The actual emission is ONE physical stderr
    line; the docstring renders it across two visual lines only
    because rst literal blocks wrap on the page width. Agents
    grepping stderr should match the literal substring
    ``more — use --format=json for full details`` as the
    fidelity-available signal::

        protokit lint: warning [{category}]: ... and {N} more — use --format=json for full details

    Both the ``{category}`` and ``{message}`` slots are passed
    through ``_safe_for_stderr`` before ``click.echo`` as a
    defense-in-depth measure: construction-time sanitization in
    engine.py / cli.py already collapses control characters in the
    message field, and the ``category`` field is typed as a closed
    ``Literal[...]`` set whose five values are all ASCII tokens — but
    Python does not enforce ``Literal`` at runtime, so a future
    emission site that constructs a ``LintRuntimeWarning`` with a
    control-character-bearing category string would otherwise bypass
    the boundary. Sanitizing both slots keeps the stderr boundary
    symmetric and immune to that future-emission-site regression.

    A non-positive ``_LINT_HUMAN_SUMMARIZATION_THRESHOLD`` is
    clamped to ``1`` at function entry so the summarization math
    stays well-defined under accidental tuning to ``0`` or negative
    values (zero would fire summary on the first warning with
    "and N more" framing implying prior emissions; negative would
    overcount remaining by ``abs(threshold)``).

    This hook is **NOT** gated by ``--quiet``: ``--quiet``
    suppresses findings on stdout, not warnings on stderr.
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
        "  Declare custom annotation rules in pyproject "
        "(no Python required):\n\n"
        "    # pyproject.toml:\n\n"
        "    # [[tool.protokit.lint.custom_annotation_rules]]\n\n"
        "    # rule_suffix    = \"audit-required\"\n\n"
        "    # option         = \"example.audit_level\"\n\n"
        "    # element_kinds  = [\"method\"]\n\n"
        "    # allowed_values = [\"LOW\", \"HIGH\", \"CRITICAL\"]\n\n"
        "    # severity       = \"error\"\n\n"
        "    protokit lint --proto service.proto -I proto/\n\n"
        "    # Materializes custom/audit-required rule_id; see\n\n"
        "    # tests/schema/lint/cli/cli_fixtures/d6d_custom_annotation/\n\n"
        "    # for the canonical worked example.\n\n"
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
        "  Disable a single rule for this invocation (R9b per-rule disable):\n\n"
        "    protokit lint --disable-rule naming/snake-case-fields "
        "schema.descriptor_set\n\n"
        "  Run a pure opt-in workflow — --no-builtin-rules starts the "
        "engine empty, so the rules must come from --rule-pack "
        "(--enable-rule does NOT load rules; with no pack loaded the "
        "run exits 2 with error[lint-no-rules]):\n\n"
        "    protokit lint --no-builtin-rules --rule-pack acme.lint_rules "
        "schema.descriptor_set\n\n"
        "  Inspect R9b runtime_warnings (unknown rule id / contradiction):\n\n"
        "    protokit lint --format=json --disable-rule custom/audit-required "
        "schema.descriptor_set\n\n"
        "EXIT CODES:\n\n"
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
         "structured payloads natively. "
         "Zero-count severity rows are suppressed; only non-zero "
         "severities appear below the `statistics:` marker.",
)
@click.option(
    "--quiet",
    "quiet",
    is_flag=True,
    default=False,
    help="Suppress findings on stdout; exit code still reflects "
         "the standard exit-code ladder (0 clean, 1 ERROR or "
         "WARNING > --max-warnings, 2 lint-internal error). Hard "
         "mutex with "
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
    # Expand `~` to the home directory at the Click input boundary
    # (per the normalize-at-input-boundary learning under
    # docs/solutions/best-practices/). Without this,
    # `--config ~/config.toml` would fail with "does not exist"
    # because Click's Path() does not expand tildes itself.
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
         "The descriptor pool still loads all files (filtering "
         "applies to findings emission, not pool loading); "
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
@click.option(
    "--no-builtin-rules",
    "no_builtin_rules",
    is_flag=True,
    default=False,
    help="Skip loading BUILTIN_PACKS. When set, the "
         "lint engine starts empty and only user-supplied packs via "
         "--rule-pack MODULE contribute rules. Use cases: "
         "(a) opt out of the built-in rule set while triaging "
         "newly-fired rules (pair with --min-severity warning to "
         "demote on a rule-by-rule basis via "
         "[tool.protokit.lint.severities]); (b) run a pure "
         "user-pack workflow without protokit's defaults. Pyproject "
         "equivalent: [tool.protokit.lint] no_builtin_rules = true. "
         "CLI takes precedence over pyproject when both are set. "
         "Warning: if neither BUILTIN_PACKS nor --rule-pack supplies "
         "any rules, the lint engine exits 2 with "
         "'error[lint-no-rules]:' rather than emitting zero findings.",
)
@click.option(
    "--disable-rule",
    "disable_rules",
    multiple=True,
    metavar="RULE_ID",
    envvar="PROTOKIT_DISABLE_RULE",
    show_envvar=True,
    help="Disable a specific rule_id for this invocation "
         "(repeatable). Accepts canonical 'pack/rule-suffix' "
         "(e.g., 'naming/snake-case-fields') and custom forms "
         "('custom/<suffix>' for all-kinds disable; "
         "'custom/<suffix>__<kind>' for per-kind disable). The "
         "rule is removed from the composed profile's rule_ids "
         "BEFORE the engine walks any descriptors, so it never "
         "fires. Pyproject equivalent: [tool.protokit.lint] "
         "disabled_rules = [...]. Precedence: any disable from "
         "any tier wins (polarity-first); within polarity, CLI > "
         "pyproject. Cross-tier --enable-rule R + pyproject "
         "disabled_rules ⊃ R emits a "
         "'contradictory_disable_config' runtime warning. The "
         "alternative '[tool.protokit.lint.severities] R = \"off\"' "
         "produces the same effect (severity-off sentinel). "
         "Env-var: PROTOKIT_DISABLE_RULE accepts space-separated "
         "rule_ids (e.g., PROTOKIT_DISABLE_RULE=\"naming/snake-case-fields "
         "imports/unused\"); comma-separation is NOT supported. "
         "Use --format=json to inspect runtime_warnings for "
         "'unknown_rule_id' (typo / removed-rule signal) and "
         "'contradictory_disable_config' (polarity conflict) "
         "diagnostics.",
)
@click.option(
    "--enable-rule",
    "enable_rules",
    multiple=True,
    metavar="RULE_ID",
    envvar="PROTOKIT_ENABLE_RULE",
    show_envvar=True,
    help="Prevent an R9b disable directive from suppressing the named "
         "rule (repeatable). Accepts the same rule_id shapes "
         "as --disable-rule. Pyproject equivalent: "
         "[tool.protokit.lint] enabled_rules = [...]. Does NOT add "
         "rules to the profile — use --profile to select a profile "
         "that includes the rule, OR --rule-pack to load a rule pack. "
         "With --no-builtin-rules, the rule must come from a "
         "--rule-pack module; otherwise it remains unloaded and emits "
         "an 'unknown_rule_id' warning. The polarity-first precedence "
         "rule means any disable (from any tier) wins — --enable-rule "
         "does NOT override a pyproject 'disabled_rules' or "
         "'[severities] = \"off\"' disable. To bypass pyproject "
         "entirely, use --no-config (WARNING: --no-config drops ALL "
         "pyproject configuration, not just disabled_rules). To "
         "partially override, edit your pyproject directly. "
         "Env-var: PROTOKIT_ENABLE_RULE accepts space-separated "
         "rule_ids; comma-separation is NOT supported. "
         "Use --format=json to inspect runtime_warnings for "
         "'unknown_rule_id' (typo / removed-rule signal) and "
         "'contradictory_disable_config' (polarity conflict) "
         "diagnostics.",
)
@click.option(
    "--version",
    is_flag=True,
    is_eager=True,
    expose_value=False,
    callback=_print_lint_version,
    help="Show ``protokit X.Y.Z (parity: buf v<PIN>)`` and exit. The "
         "buf-parity pin is the version that ``tests/parity/`` "
         "verifies against in CI; surfacing it here lets users "
         "verify the parity reference without reading CI YAML.",
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
    no_builtin_rules: bool,
    disable_rules: tuple[str, ...],
    enable_rules: tuple[str, ...],
) -> None:
    """Lint INPUTS for style and policy violations.

    By default, INPUTS are pre-built ``.descriptor_set`` files
    (``protoc --descriptor_set_out`` output). Pass ``--proto`` to
    treat them as ``.proto`` source files compiled at invocation
    time. Multiple inputs are merged into a single descriptor pool
    with first-occurrence-wins deduplication on ``fd.name``.

    """
    # --config and --no-config are mutually exclusive. Click-level
    # mutex emits the 'Usage:' prefix and exits 2 — distinct from
    # --config's loader-side errors which carry the
    # error[lint-pyproject-config-load]: prefix.
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
    # --no-exclude wins over --exclude. When both are supplied, drop
    # the --exclude patterns silently after announcing the override on
    # stderr (mirrors the --quiet/--statistics soft-mutex pattern
    # above).
    if no_exclude and exclude_patterns:
        click.echo(
            "warning[lint-cli]: --no-exclude clears --exclude patterns "
            "(--no-exclude wins)",
            err=True,
        )
    # Load [tool.protokit.lint] from pyproject.toml. If
    # load_pyproject_config raises SystemExit (any shadow path,
    # parse error), it never returns and the CLI exits 2 with the
    # error[lint-pyproject-config-load]: stable prefix.
    pyproject_config = load_pyproject_config(
        explicit_path=config_path,
        no_config=no_config,
    )
    # Validate the pyproject table and merge with CLI overrides into a
    # single ResolvedLintConfig carrier. CLI-default values for
    # --profile and --format are indistinguishable from explicit user
    # choices by value alone (defaults: "default" and "human"), so we
    # rely on Click's parameter-source detection to know whether the
    # user actually typed the flag. COMMANDLINE, ENVIRONMENT, and
    # DEFAULT_MAP all count as "explicit" — env vars like
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
    # --exclude / --no-exclude → cli_overrides["exclude"]. See
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
    # --no-builtin-rules CLI flag. The flag is_flag=True with
    # default=False; Click delivers True/False unambiguously. Use
    # parameter-source detection to distinguish "user typed --no-builtin-rules"
    # from "CLI default" — only honor it as an explicit override when the
    # user genuinely typed it (or set it via env / DEFAULT_MAP). When the
    # user did not set it explicitly, pass ``None`` so pyproject takes
    # precedence per the ResolvedLintConfig.from_dict contract.
    no_builtin_rules_explicit = (
        ctx.get_parameter_source("no_builtin_rules") in explicit_sources
    )
    # Click multiple=True natural empty-tuple sentinel (no
    # ParameterSource needed). The user cannot produce `()` by typing
    # the flag — Click requires a value with each ``--disable-rule``
    # invocation — so `not disable_rules` is a clean "user did not
    # pass this flag" test. Passing the literal empty tuple to
    # ResolvedLintConfig.from_dict would behave identically (the
    # unified disable set unions in an empty frozenset); the ``None``
    # sentinel is preferred for symmetry with the other CLI overrides.
    cli_disable_value = tuple(disable_rules) if disable_rules else None
    cli_enable_value = tuple(enable_rules) if enable_rules else None
    cli_overrides: dict[str, Any] = {
        # Handed over RAW: `ResolvedLintConfig.from_dict` runs
        # `_coerce_profile` on this tier, which strips + lowercases AND
        # resolves the buf-compatibility aliases (`basic`, `minimal`).
        # A local `.strip().lower()` here used to duplicate half of that
        # — enough to make the CLI look normalized while the alias half
        # silently applied to pyproject only. One boundary, both halves.
        "profile": (profile_name,) if profile_explicit else None,
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
        "no_builtin_rules": (
            no_builtin_rules if no_builtin_rules_explicit else None
        ),
        "disabled_rules": cli_disable_value,
        "enabled_rules": cli_enable_value,
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

    ``resolved`` is a ``ResolvedLintConfig`` carrier: the merged
    result of CLI flags + pyproject ``[tool.protokit.lint]`` +
    built-in defaults, with per-key precedence already applied.
    Consumers in this function:

    - ``resolved.profile`` — iterated to compose multi-profile
      pyproject configurations (single-profile is the common case).
    - ``resolved.min_severity`` + ``resolved.min_severity_source`` —
      drives the relaxation diagnostic emitted as a structured
      ``LintRuntimeWarning``.
    - ``resolved.max_warnings``, ``resolved.format`` — drive the
      exit-code ladder and formatter dispatch.
    """
    if use_proto:
        # ``include_source_info=True`` enables the deprecated-replacement
        # rule family (and any future comment-aware rules) to read
        # proto-source leading comments via the ``_comments``
        # helpers. Cost is ~10-30% descriptor-set size per cross-runtime
        # measurement; paid universally on every proto-mode lint
        # invocation. Non-lint consumers (``protokit compat``, codegen,
        # direct Python API) keep the zero-cost contract via the
        # parameter default.
        result = compile_protos_to_result(
            paths=list(inputs),
            proto_paths=list(proto_paths),
            include_source_info=True,
        )
        # Surface non-error info/warning diagnostics to stderr so
        # protoxy fallback notices and import-resolution warnings
        # don't get silently swallowed — agents in --proto mode see
        # all backend diagnostics, not just errors. Error diagnostics
        # are rendered below right before the exit-2 stable-prefix
        # line.
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
                # ``diag.message`` is a protokit-authored summary
                # ("protoc compilation failed"); the actionable text —
                # ``file:line:col: Expected field name.`` — lives ONLY on
                # the structured ``command``/``exit_code``/``stderr``
                # fields. Nothing else renders them: no formatter reads
                # ``.stderr``, and ``error_exit_with_code`` below raises
                # SystemExit before formatter dispatch, so not even
                # ``--format=json`` can recover it. Without these
                # continuation lines the "see stderr for details"
                # promise is unbacked and the user is left to re-run the
                # compiler by hand to learn what is wrong with the file.
                #
                # Compiler output is EXTERNAL, untrusted input, so it
                # goes through ``_safe_for_stderr`` (control characters,
                # including the newlines of a multi-line protoc dump,
                # collapse to spaces) per the stderr-forge discipline in
                # docs/solutions/security-issues/
                # module-name-newline-injection-stderr-forge-2026-05-07.md
                # — a compiler message must not be able to synthesise a
                # line beginning with a stable ``error[lint-...]:``
                # prefix that CI greps. Continuation lines are indented
                # so they read as detail for the diagnostic above and
                # can never be mistaken for a stable-prefix line.
                if diag.command is not None or diag.exit_code is not None:
                    cmd_str = (
                        " ".join(diag.command)
                        if diag.command is not None
                        else ""
                    )
                    exit_str = (
                        "" if diag.exit_code is None else str(diag.exit_code)
                    )
                    click.echo(
                        f"  cmd={_safe_for_stderr(cmd_str)!r} "
                        f"exit={exit_str}",
                        err=True,
                    )
                if diag.stderr:
                    click.echo(
                        f"  {_safe_for_stderr(diag.stderr)}",
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
    #
    # When ``resolved.no_builtin_rules`` is True (CLI
    # ``--no-builtin-rules`` or pyproject ``no_builtin_rules = true``),
    # skip the auto-load loop entirely. User packs supplied via
    # ``--rule-pack`` still load. If neither builtin packs nor user
    # packs are loaded, the engine starts empty and the no-rules
    # exit-2 ladder catches it downstream.
    engine = LintEngine()
    # Track every successfully-loaded pack (built-ins + user packs)
    # so we can introspect declared profiles for the unknown-profile
    # diagnostic and contributing rule_ids for the multi-pack
    # provenance line.
    loaded_packs: list[ModuleType] = []
    if not resolved.no_builtin_rules:
        for pack in BUILTIN_PACKS:
            try:
                engine.load_rule_pack(pack)
            except (DuplicateRuleError, TypeError, AttributeError) as exc:
                error_exit_with_code(
                    "rule-pack-load",
                    f"kind=builtin: built-in pack {pack.__name__!r} failed "
                    f"to load: {_safe_for_stderr(_scrub_exc_message(exc))}",
                )
            loaded_packs.append(pack)

    # Synthetic ``custom/<suffix>`` rules from
    # ``[[tool.protokit.lint.custom_annotation_rules]]``. Loaded BEFORE
    # ``--rule-pack`` modules so that a user pack that accidentally
    # declares a ``custom/<suffix>`` rule_id (reserved namespace)
    # collides via the engine's DuplicateRuleError ladder, surfacing
    # the mistake at load time with the existing rule-pack-load exit
    # code. ``--no-builtin-rules`` does NOT gate this step — synthetic
    # rules are user-declared, not built-in, so the no-builtin-rules
    # flag's "skip BUILTIN_PACKS" semantics don't apply.
    synthetic_module: ModuleType | None = None
    if resolved.custom_annotation_rules:
        synthetic_module = build_synthetic_module(
            resolved.custom_annotation_rules, engine,
        )
        if synthetic_module is not None:
            try:
                engine.load_rule_pack(synthetic_module)
            except (DuplicateRuleError, TypeError, AttributeError) as exc:
                error_exit_with_code(
                    "rule-pack-load",
                    (
                        f"kind=synthetic: synthetic custom-annotation pack "
                        f"failed to load: {_safe_for_stderr(_scrub_exc_message(exc))}"
                    ),
                )

    for module_name in rule_packs:
        # Stderr load-banner: every --rule-pack invocation emits
        # an advisory line so the trust delegation is observable
        # — a security mitigation for the arbitrary-Python-execution
        # surface that --rule-pack opens. Stderr diagnostic; not
        # gated by --quiet (which suppresses findings stdout only).
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
        user_pack = _load_user_rule_pack(module_name, engine)
        # CLI-level dedup parallels ``LintEngine.load_rule_pack``'s
        # idempotency at ``engine.py:241-242``: when a user passes
        # ``--rule-pack=<pack>`` for a pack already in BUILTIN_PACKS,
        # the engine no-ops the second load, but ``loaded_packs``
        # would still get a duplicate appended. That breaks the
        # multi-pack provenance line's ``zip(loaded_packs_tuple,
        # _active_rule_ids_per_pack(...).values(), strict=True)``
        # below — the helper dict is keyed by ``pack.__name__`` (so
        # it dedups), but the tuple would not, yielding mismatched
        # zip arguments. The dedup here keeps both data structures
        # consistent. The latent helper bug was surfaced empirically
        # when ``package_same`` flipped into BUILTIN_PACKS — a parity
        # gate caught the helper's mismatched-zip assumption at
        # implementation time, not in advance.
        if user_pack.__name__ not in {p.__name__ for p in loaded_packs}:
            loaded_packs.append(user_pack)

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
                    f"{_safe_for_stderr(_scrub_exc_message(exc))})",
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

    # Union synthetic rule_ids into the composed profile so the
    # engine's profile filter activates them. Synthetic rules are
    # always-on when configured — they don't participate in the
    # per-profile membership table because they originate from
    # pyproject array-of-tables entries, not from packs declaring
    # profile membership via @lint_rule(profiles=...). The augmentation
    # happens AFTER profile composition (so the user's --profile choice
    # is preserved) and BEFORE the [severities] overlay (so user
    # demotion via [tool.protokit.lint.severities] applies).
    if resolved.custom_annotation_rules:
        synthetic_ids = synthetic_rule_ids(resolved.custom_annotation_rules)
        if synthetic_ids:
            composed_profile = dataclasses.replace(
                composed_profile,
                rule_ids=composed_profile.rule_ids | synthetic_ids,
            )

    # Apply the per-rule severities overlay. User pyproject
    # ``[tool.protokit.lint.severities]`` always wins on collision
    # with the composed profile's rule_severity_overrides. The overlay
    # must happen BEFORE min_severity replacement below so the engine
    # sees the final composed profile shape; ordering does not affect
    # correctness today since min_severity and rule_severity_overrides
    # are independent fields, but pinning the order to "user severities
    # first" makes the precedence explicit.
    #
    # Keys in ``resolved.severities`` that don't match any rule_id
    # in the composed profile are diagnosed below (after engine.run)
    # via a synthesized ``severities_unloaded_rule`` runtime warning;
    # see :class:`LintRuntimeWarning.category` docstring.
    if resolved.severities:
        composed_profile = dataclasses.replace(
            composed_profile,
            rule_severity_overrides={
                **composed_profile.rule_severity_overrides,
                **resolved.severities,
            },
        )
    # Snapshot the profile's loaded rule_ids BEFORE R9b disable
    # subtraction, so the severities_unloaded_rule diagnostic below
    # only flags severities keys that don't match ANY rule in the
    # composed profile — not rule_ids that exist but the user has
    # explicitly disabled. Without this snapshot, a user who sets
    # both ``disabled_rules = ["R"]`` AND ``[severities] R = "warning"``
    # would receive TWO warnings (the contradictory_disable_config
    # warning from from_dict AND a spurious severities_unloaded_rule
    # from below); the snapshot ensures the latter only fires for
    # genuinely unknown rule_ids.
    pre_disable_rule_ids = composed_profile.rule_ids
    # Load-bearing R9b profile-augmentation step. Subtract the unified
    # disabled_rules set (severity-"off" sentinel + pyproject
    # disabled_rules + CLI --disable-rule, with custom-prefix expansion
    # already applied) from the composed profile's rule_ids BEFORE
    # handing the profile to the engine. This is the actuation of the
    # R9b disable-propagation contract: from_dict produced the unified
    # set, and this is where the engine's profile filter loses the
    # disabled rule_ids. Without this step the from_dict bookkeeping
    # silently no-ops at runtime — caught by
    # ``tests/schema/lint/cli/test_cli_r9b_profile_augmentation.py``.
    if resolved.disabled_rules:
        composed_profile = dataclasses.replace(
            composed_profile,
            rule_ids=composed_profile.rule_ids - resolved.disabled_rules,
        )
    # Collect unknown keys for the post-engine.run advisory
    # emission. Two guards apply:
    # 1. Subtract ``pre_disable_rule_ids`` (the union of all loaded
    #    packs' rule_ids in the active profile BEFORE R9b disable
    #    subtraction): prevents a spurious severities_unloaded_rule
    #    for a rule the user explicitly disabled AND overrode in
    #    [severities] — the from_dict contradictory_disable_config
    #    warning already attributes the contradiction.
    # 2. Also subtract ``resolved.disabled_rules``: when a rule_id
    #    appears in BOTH disabled_rules AND [severities] with a
    #    non-off value, the rule is genuinely unknown (not in the
    #    composed profile at all). Without this second guard, such a
    #    rule fires BOTH contradictory_disable_config AND
    #    severities_unloaded_rule, which is redundant — the
    #    contradictory_disable_config warning is the canonical
    #    attribution. The subtraction ensures zero
    #    severities_unloaded_rule warnings for rule_ids that are
    #    already covered.
    # Empty severities → empty tuple (no extra branch).
    severities_unloaded_rule_ids: tuple[str, ...] = tuple(
        sorted(
            (set(resolved.severities) - pre_disable_rule_ids)
            - resolved.disabled_rules,
        ),
    )

    # Apply min_severity override. Pure numeric override that
    # replaces the composed profile's min_severity. The relaxation
    # message (if the override actually relaxes the floor) is
    # computed HERE and emitted post-engine.run as a structured
    # LintRuntimeWarning(category="min_severity_relaxed"). The
    # message templates live on ResolvedLintConfig.relaxation_message
    # per the cross-format-enum-string-parity learning so every
    # formatter emits identical text.
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

    # Loud-failure checks: no-rules wins over unknown-profile when
    # both predicates would fire — the user can't meaningfully fix
    # profile selection without rules to select from.
    if not engine.has_rules:
        error_exit_with_code(
            "no-rules",
            "no lint rules loaded — supply --rule-pack with a pack "
            "exposing RULES, or rely on the built-in BUILTIN_PACKS "
            "(see protokit.schema.lint.rules.BUILTIN_PACKS).",
        )
    # R9b directives disabled every rule in the resolved profile.
    # This guard fires BEFORE the unknown-profile guard so the more
    # specific error wins — the profile WAS declared, the user just
    # disabled all its rules.
    if pre_disable_rule_ids and not composed_profile.rule_ids:
        n = len(pre_disable_rule_ids)
        profile_display = _safe_for_stderr(
            resolved.profile[0]
            if len(resolved.profile) == 1
            else "+".join(resolved.profile)
        )
        error_exit_with_code(
            "no-rules-after-disable",
            (
                f"profile {profile_display!r} had {n} rule(s) but R9b "
                f"directives (disabled_rules / [severities]='off' / "
                f"--disable-rule) disabled all of them; no rules remain "
                f"to run. Review your disable directives or use "
                f"--no-config to bypass pyproject."
            ),
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

    # Multi-pack composition stderr provenance line. Gated on
    # len(loaded_packs) >= 2 — single-pack default emits no line
    # (it's not composing anything).
    if len(loaded_packs_tuple) >= 2:
        active_per_pack = _active_rule_ids_per_pack(
            loaded_packs_tuple, composed_profile.rule_ids,
        )
        # Sanitize every attacker-influenced slot before emission: rule_ids
        # come from user pack metadata (`spec.rule_id`); profile names come
        # from pyproject or --profile. Both flow into this stderr line via
        # f-string interpolation and would otherwise allow U+2028/U+2029
        # injection that bypasses chained `.replace()` and that `_safe_module_name`
        # already addresses for the pack-name slot. Mirrors the full-slot
        # sanitization posture per the module-name-newline-injection learning.
        per_pack_segments = [
            (
                f"{_safe_module_name(pack)}="
                f"[{','.join(_safe_for_stderr(rid) for rid in rule_ids)}]"
            )
            for pack, rule_ids in zip(
                loaded_packs_tuple, active_per_pack.values(), strict=True,
            )
        ]
        # Render multi-profile as "default+strict-naming" for the
        # provenance line so the resolved set is observable.
        provenance_profile = _safe_for_stderr(
            resolved.profile[0]
            if len(resolved.profile) == 1
            else "+".join(resolved.profile)
        )
        click.echo(
            f"protokit lint: profile {provenance_profile!r} from "
            + "; ".join(per_pack_segments),
            err=True,
        )

    # File-level exclusion. Apply `resolved.exclude` patterns to the
    # post-compile `result.root_files` BEFORE invoking the engine.
    # The descriptor POOL still loads every file (so transitive
    # imports resolve), but the engine only walks files that survive
    # the filter. When zero files survive AND the user passed inputs
    # at all, emit `LintRuntimeWarning(category="all_files_excluded")`
    # CLI-side and short-circuit `engine.run` with an empty report;
    # downstream rendering still fires so the warning surfaces in
    # every formatter.
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
            # The all_files_excluded message is source-attributed via
            # ResolvedLintConfig.all_files_excluded_message, so users
            # see whether the dropping patterns came from --exclude,
            # pyproject, or both. Patterns are newline-sanitized
            # inside the helper.
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

    # Post-engine append for `min_severity_relaxed`. By alphabetical
    # ordering, this comes AFTER any `all_files_excluded` already
    # attached above (alphabetical: all_files_excluded <
    # min_severity_relaxed). Engine-emitted categories
    # (`rule_exception`, `unloaded_rule`) come first by emission
    # order; CLI-emitted categories are appended in alphabetical
    # sequence here.
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

    # Synthesize ``severities_unloaded_rule`` runtime warnings for any
    # ``severities`` keys that don't match a rule_id in the composed
    # profile. See :class:`LintRuntimeWarning.category` docstring for
    # the per-emit-site contract. The schema_version 0.2 → 0.3 bump
    # in ``_LINT_JSON_SCHEMA_VERSION`` is the consumer-facing
    # wire-format signal that switch tables need re-checking.
    # Sanitize the rule_id (flows verbatim into lint_json/lint_sarif
    # wire formats; json.dumps does NOT escape U+2028/U+2029) per the
    # dual-sanitization model.
    if severities_unloaded_rule_ids:
        new_warnings = tuple(
            LintRuntimeWarning(
                category="severities_unloaded_rule",
                rule_id=_safe_for_stderr(rid),
                message=(
                    f"rule {_safe_for_stderr(rid)!r} is named in "
                    f"[tool.protokit.lint.severities] but is not "
                    f"in the composed profile — the severity override "
                    f"has no effect"
                ),
            )
            for rid in severities_unloaded_rule_ids
        )
        report = dataclasses.replace(
            report,
            runtime_warnings=report.runtime_warnings + new_warnings,
        )

    # Append the contradictory_disable_config warnings that
    # ``ResolvedLintConfig.from_dict`` accumulated during R9b
    # precedence resolution. They live on ``resolved.runtime_warnings``
    # (a frozen-dataclass-safe tuple snapshot per __post_init__) so
    # they reach the formatter pipeline like any engine-emitted
    # warning. Empty tuple in the common no-contradictions case.
    if resolved.runtime_warnings:
        report = dataclasses.replace(
            report,
            runtime_warnings=(
                report.runtime_warnings + resolved.runtime_warnings
            ),
        )

    # Synthesize ``unknown_rule_id`` warnings for any R9b directive
    # (disabled_rules / enabled_rules from pyproject OR
    # --disable-rule / --enable-rule from CLI, post-normalization
    # and post-custom-prefix-expansion) naming a rule_id that does
    # not exist in the engine's ``_loaded_specs`` registry after
    # all rule-pack loading. Mirrors the existing
    # ``severities_unloaded_rule`` pattern above: the orchestration
    # layer has the full loaded-rule universe and is the natural
    # site for the diff. Lenient-with-warning — the unknown id has
    # already been silently dropped from the effective set by
    # from_dict's polarity-precedence resolution, so no behavior
    # change beyond the diagnostic.
    loaded_rule_ids = engine.loaded_rule_ids
    unknown_r9b_rule_ids: tuple[str, ...] = tuple(
        sorted(
            (resolved.disabled_rules | resolved.enabled_rules)
            - loaded_rule_ids,
        ),
    )
    if unknown_r9b_rule_ids:
        def _r8c_message(rid: str) -> str:
            # Detect mangled-custom-form misuse: first-kind synthetic rules
            # register under the BARE form ("custom/X"), not "custom/X__<first_kind>".
            # A user writing the mangled form expecting per-kind disable on the first
            # kind silently fails; the unknown_rule_id diagnostic should mention the convention.
            safe_rid = _safe_for_stderr(rid)
            if "__" in rid and rid.startswith("custom/"):
                return (
                    f"rule {safe_rid!r} is named in an R9b directive "
                    f"(disabled_rules / enabled_rules / --disable-rule / --enable-rule) "
                    f"but does not match any loaded rule. Note: first-kind custom rules "
                    f"register under the bare 'custom/<suffix>' form; the '__<kind>' "
                    f"mangled form addresses only subsequent kinds. Verify the kind name "
                    f"OR use the bare form to disable all kinds at once."
                )
            return (
                f"rule {safe_rid!r} is named in an R9b directive "
                f"(disabled_rules / enabled_rules / "
                f"--disable-rule / --enable-rule) but does not "
                f"match any loaded rule — the directive has no "
                f"effect"
            )

        unknown_warnings = tuple(
            LintRuntimeWarning(
                category="unknown_rule_id",
                rule_id=_safe_for_stderr(rid),
                message=_r8c_message(rid),
            )
            for rid in unknown_r9b_rule_ids
        )
        report = dataclasses.replace(
            report,
            runtime_warnings=report.runtime_warnings + unknown_warnings,
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

    # CLI-side post-format hook for ``--format=human``. The machine
    # formatters (``lint_json`` / ``lint_junit`` / ``lint_sarif``)
    # embed ``runtime_warnings`` in their structured payloads;
    # ``lint_human`` is intentionally pure (returns the findings
    # string), so re-surfacing the warnings to stderr is CLI-layer
    # policy. The hook is NOT gated by ``--quiet`` (warnings on
    # stderr stay visible; ``--quiet`` suppresses findings on stdout).
    if resolved.format == "human":
        _emit_human_runtime_warnings(report)

    if statistics and resolved.format == "human" and not quiet:
        _emit_statistics_footer(report)

    # V33 (0.15.1): the analysis-completeness gate runs BEFORE the
    # findings gates. Exit 1 asserts "the tool ran and found a
    # problem"; that claim is unavailable when a rule raised or was
    # never loaded, because the findings we do have are a lower bound
    # on an unknown total. A crashing rule pack produces *zero*
    # findings, so both the `has_error` gate and `--max-warnings 0`
    # saw a clean run and exited 0 — a CI gate that silently stopped
    # gating. The report has already been rendered above; only the
    # verdict changes.
    #
    # Deliberately narrow, and deliberately throwaway: the 0.16.0
    # `_trust` seam replaces this with one predicate consulted by
    # every renderer and every exit path. Do not grow it here.
    blocking = [
        w for w in report.runtime_warnings
        if w.category in _INCOMPLETE_ANALYSIS_CATEGORIES
    ]
    if blocking:
        categories = ", ".join(sorted({w.category for w in blocking}))
        error_exit_with_code(
            "analysis-incomplete",
            f"{len(blocking)} of {len(report.runtime_warnings)} runtime "
            f"warning(s) mean a rule did not run ({categories}); the "
            "findings this run produced are a lower bound, so a clean "
            "result would not mean the schema is clean",
        )

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
    should not parse individual rows as a stable contract — use the
    machine formats (``json`` / ``junit`` / ``sarif``) for
    structured counts.
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
