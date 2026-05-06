"""``protokit lint`` click subcommand — Delivery 3, Unit 2.

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

U2 ships the minimal end-to-end pipeline:
    1. Resolve inputs via descriptor-set or ``--proto`` source mode.
    2. Auto-load ``BUILTIN_PACKS`` (currently ``naming``).
    3. Derive the default profile via ``LintProfile.from_pack``.
    4. Run ``engine.run`` over the compile result.
    5. Render via ``lint_human`` and echo to stdout.

U3 lifts the hard-coded auto-load + default profile into the
flag-driven version (``--rule-pack`` / ``--profile`` /
``--min-severity``) and adds the R9 / R11 / R25 paths. U4a wires
the R20 exit-code ladder + ``--max-warnings`` / ``--statistics``
/ ``--quiet`` / ``--format``. U4b adds the three machine
formatters. Until U4a lands, exit code is 0 unconditionally on
successful pipeline runs (the KD-10 invariant requires only
"never 2 from internal CLI errors", which holds).
"""

from __future__ import annotations

from pathlib import Path

import click

# Side-effect import: registers lint_human (and, post-U4b,
# lint_json/lint_junit/lint_sarif) in the formatter registry.
# MUST happen at module top so registration runs at protokit.cli
# load time, before click dispatches the subcommand callback.
import protokit.formatters._builtin_lint  # noqa: F401  -- import for side effect
from protokit.formatters import FormatterContext
from protokit.formatters._builtin_lint import lint_human
from protokit.schema.compile import compile_protos_to_result
from protokit.schema.lint._cli_utils import (
    _load_descriptor_sets_to_result,
    error_exit_with_code,
)
from protokit.schema.lint.engine import LintEngine
from protokit.schema.lint.model import LintProfile
from protokit.schema.lint.rules import BUILTIN_PACKS


@click.command(
    "lint",
    short_help="Lint a protobuf schema for style and policy violations.",
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
    help="Import path for .proto compilation (repeatable). "
         "Only applies with --proto. Analogous to protoc -I.",
)
def main(
    inputs: tuple[Path, ...],
    use_proto: bool,
    proto_paths: tuple[str, ...],
) -> None:
    """Lint INPUTS for style and policy violations.

    By default, INPUTS are pre-built ``.descriptor_set`` files
    (``protoc --descriptor_set_out`` output). Pass ``--proto`` to
    treat them as ``.proto`` source files compiled at invocation
    time. Multiple inputs are merged into a single descriptor pool
    with first-occurrence-wins deduplication on ``fd.name``.

    Auto-loads the ``naming`` rule pack from ``BUILTIN_PACKS``.
    See ``BUILTIN_PACKS`` in ``protokit.schema.lint.rules`` for
    the auto-load surface (KD-9 anchor).
    """
    # Resolve inputs into a CompileResult.
    if use_proto:
        result = compile_protos_to_result(
            paths=list(inputs),
            proto_paths=list(proto_paths),
        )
        if any(d.level == "error" for d in result.diagnostics):
            # Render the error diagnostics so the user sees what
            # went wrong before the exit-2 stable-prefix line.
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

    # Auto-load BUILTIN_PACKS and derive the default profile.
    # U3 lifts these hard-coded values into flag-driven equivalents.
    engine = LintEngine()
    for pack in BUILTIN_PACKS:
        engine.load_rule_pack(pack)
    profile = LintProfile.from_pack(BUILTIN_PACKS[0], "default")

    # Run the engine and render via lint_human.
    report = engine.run(result, profile=profile)
    ctx = FormatterContext(subcommand="lint")
    output = lint_human(report, ctx)
    if output:
        click.echo(output)
