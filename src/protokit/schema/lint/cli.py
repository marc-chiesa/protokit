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
from pathlib import Path
from types import ModuleType

import click

# Importing ``lint_human`` registers all four lint formatters in the
# formatter registry as a side effect — the ``_builtin_lint`` module
# body runs ``_register_builtin`` calls at import time. This MUST
# happen at module top so registration runs at ``protokit.cli`` load
# time, before click dispatches the subcommand callback.
from protokit.formatters import FormatterContext
from protokit.formatters._builtin_lint import lint_human
from protokit.schema.compile import compile_protos_to_result
from protokit.schema.lint._cli_utils import (
    _active_rule_ids_per_pack,
    _declared_profiles_per_pack,
    _load_descriptor_sets_to_result,
    _load_user_rule_pack,
    error_exit_with_code,
)
from protokit.schema.lint.engine import LintEngine
from protokit.schema.lint.model import (
    _SEVERITY_RANK,
    LintProfile,
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
        "  Lint a pre-built descriptor set:\n"
        "    protokit lint schema.descriptor_set\n\n"
        "  Lint .proto sources directly (compiled at invocation):\n"
        "    protokit lint --proto api.proto -I src/\n\n"
        "  Lint multiple descriptor sets merged into one pool:\n"
        "    protokit lint a.descriptor_set b.descriptor_set\n\n"
        "  Load a user rule pack on top of the built-in canary:\n"
        "    protokit lint --rule-pack acme.lint_rules schema.descriptor_set\n\n"
        "EXIT CODES (D3 U2/U3 — interim contract):\n\n"
        "  0 = pipeline ran (regardless of finding count; the R20\n"
        "      ladder ships in U4a where 0/1/2 will reflect findings\n"
        "      vs --max-warnings vs internal errors).\n"
        "  2 = lint-internal error (see error[lint-CODE]: stderr line\n"
        "      for the stable-prefix code, or click's Usage: prefix\n"
        "      for flag-validation errors)."
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
    metavar="LEVEL",
    help="Override the composed profile's severity floor. Findings "
         "below this severity are filtered. Emits a stderr "
         "advisory line when the override is more lenient than the "
         "composed floor.",
)
def main(
    inputs: tuple[Path, ...],
    use_proto: bool,
    proto_paths: tuple[str, ...],
    rule_packs: tuple[str, ...],
    profile_name: str,
    min_severity: str | None,
) -> None:
    """Lint INPUTS for style and policy violations.

    By default, INPUTS are pre-built ``.descriptor_set`` files
    (``protoc --descriptor_set_out`` output). Pass ``--proto`` to
    treat them as ``.proto`` source files compiled at invocation
    time. Multiple inputs are merged into a single descriptor pool
    with first-occurrence-wins deduplication on ``fd.name``.

    Auto-loads ``BUILTIN_PACKS`` (the canonical ``naming`` canary
    today). User packs supplied via ``--rule-pack`` load on top.
    See ``BUILTIN_PACKS`` in ``protokit.schema.lint.rules`` for the
    auto-load surface (KD-9 anchor) and the plan's R8 for the
    user-pack wire-format contract.
    """
    # Resolve inputs into a CompileResult.
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
        for diag in result.diagnostics:
            if diag.level in ("info", "warning"):
                click.echo(
                    f"{diag.level}[lint-compile]: "
                    f"{diag.category}: {diag.message}",
                    err=True,
                )
        if any(d.level == "error" for d in result.diagnostics):
            for diag in result.diagnostics:
                if diag.level == "error":
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
        result = _load_descriptor_sets_to_result(inputs)

    # Build the engine and load BUILTIN_PACKS first, then any user
    # packs supplied via --rule-pack. The order matters because
    # user packs collide on rule_id with built-in packs surface as
    # DuplicateRuleError → error[lint-rule-collision]:.
    engine = LintEngine()
    for pack in BUILTIN_PACKS:
        engine.load_rule_pack(pack)

    # Track every successfully-loaded pack (built-ins + user packs)
    # so we can introspect declared profiles for R11 and contributing
    # rule_ids for R25.
    loaded_packs: list[ModuleType] = list(BUILTIN_PACKS)
    for module_name in rule_packs:
        # Stderr load-banner: every --rule-pack invocation emits
        # an advisory line so the trust delegation is observable.
        # Per the round-1 plan-review P1 finding on --rule-pack
        # security mitigation. Future U4a `--quiet` will gate this.
        click.echo(
            f"protokit lint: loading user-supplied rule pack "
            f"{module_name!r} (executes arbitrary Python from the "
            f"named module)",
            err=True,
        )
        loaded_packs.append(_load_user_rule_pack(module_name, engine))

    loaded_packs_tuple = tuple(loaded_packs)

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
    per_pack_profiles = [
        LintProfile.from_pack(pack, profile_name)
        for pack in loaded_packs_tuple
    ]
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
        # lenient (lower _SEVERITY_RANK = lower severity = more
        # lenient). U4a's --quiet will gate this.
        if (
            _SEVERITY_RANK[override_severity]
            < _SEVERITY_RANK[composed_floor]
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
    if not engine._loaded_specs:
        error_exit_with_code(
            "no-rules",
            "no lint rules loaded — supply --rule-pack with a pack "
            "exposing RULES, or rely on the built-in BUILTIN_PACKS "
            "(see protokit.schema.lint.rules.BUILTIN_PACKS).",
        )
    if not composed_profile.rule_ids:
        # Render per-pack declared profiles so the user sees what
        # profile names ARE available across the loaded packs.
        declared = _declared_profiles_per_pack(loaded_packs_tuple)
        per_pack_lines = [
            f"  {pack_name}: declared profiles = "
            f"{{{', '.join(sorted(profiles)) or '(none)'}}}"
            for pack_name, profiles in declared.items()
        ]
        error_exit_with_code(
            "unknown-profile",
            f"profile {profile_name!r} matched 0 rules across "
            f"loaded packs.\n" + "\n".join(per_pack_lines),
        )

    # R25 multi-pack composition stderr provenance line. Gated on
    # len(loaded_packs) >= 2 per origin R25 revised — single-pack
    # default emits no line (it's not composing anything).
    if len(loaded_packs_tuple) >= 2:
        active_per_pack = _active_rule_ids_per_pack(
            loaded_packs_tuple, composed_profile.rule_ids,
        )
        per_pack_segments = [
            f"{pack_name}=[{','.join(rule_ids)}]"
            for pack_name, rule_ids in active_per_pack.items()
        ]
        click.echo(
            f"protokit lint: profile {profile_name!r} from "
            + "; ".join(per_pack_segments),
            err=True,
        )

    # Run the engine.
    report = engine.run(result, profile=composed_profile)

    # Emit runtime warnings to stderr (closes U2 ce:review CLR-U2-03
    # / agent-native warning #5). Two categories surface here:
    # `rule_exception` (a rule callable raised an exception caught
    # by the engine's narrow catch tuple) and `unloaded_rule` (the
    # active profile names a rule_id not loaded into the engine —
    # reachable now that --rule-pack ships). Future U4a `--quiet`
    # will gate this.
    for warning in report.runtime_warnings:
        click.echo(
            f"warning[lint-runtime]: {warning.category}: "
            f"{warning.message}",
            err=True,
        )

    # Render via lint_human to stdout.
    ctx = FormatterContext(subcommand="lint")
    output = lint_human(report, ctx)
    if output:
        click.echo(output)
