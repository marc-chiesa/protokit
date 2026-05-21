"""CLI dedup regression test for ``--rule-pack=...field_behavior`` post-D6d U5.

Background: D6b U7 surfaced a bug at the BUILTIN_PACKS-flip of
``package_same`` where invoking ``protokit lint --rule-pack=
protokit.schema.lint.rules.package_same`` raised
``ValueError('zip() argument 2 is shorter than argument 1')`` at
the R25 multi-pack provenance line in ``cli.py``, because the CLI
``loaded_packs`` list grew a duplicate entry while the
``_active_rule_ids_per_pack`` helper dict was keyed by
``pack.__name__`` (i.e., deduped). The fix added the load-bearing
CLI-level dedup guard near the pack-loading site.

D6d U5 flips ``options.field_behavior`` into ``BUILTIN_PACKS``. The
flip exercises the same THREE coupled mechanisms documented in
:mod:`tests.schema.lint.test_cli_rule_pack_dedup_post_d6c`:

1. **CLI-level dedup** (``cli.py`` near the pack-loading guard).
2. **Engine-level idempotent load** (``engine.py``'s
   ``load_rule_pack`` short-circuit on ``module.__name__``).
3. **Profile-level frozenset union** (``model.py``'s
   ``LintProfile.compose``).

Without any of these, ``--rule-pack=protokit.schema.lint.rules.options.field_behavior``
on any fixture would raise the zip-strict ``ValueError`` once
``loaded_packs_tuple`` has at least 2 entries (always true post-D6d
because BUILTIN_PACKS itself has 8 entries — the R25 provenance line
fires unconditionally when builtin rules are enabled).

Line-number citations are deliberately omitted in this docstring to
avoid drift; the cited mechanisms are anchored at the symbol level
(``loaded_packs``, ``zip(strict=True)``, ``load_rule_pack``,
``LintProfile.compose``). Grep ``cli.py`` for ``strict=True`` to
locate the R25 provenance line.

The fixture intentionally uses an inline-only proto that does NOT
``import "google/api/field_behavior.proto"`` (the googleapis
extension proto defining the rule's target option). With the
extension absent from the compile pool,
``options/field-behavior-consistent`` short-circuits via the
``extension_unresolved`` deduplicated runtime warning, which does
NOT block the R25 provenance line from firing — the regression
guard is whether the line raises ``ValueError`` at all. The proto
itself stays hermetic against the dev environment's compile backend
since it has no external imports.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from click.testing import CliRunner

from protokit.schema.lint.cli import main as lint_main
from tests.schema.lint._cli_dedup_helpers import (
    compile_sources_to_descriptor_set,
)

_PROTO_TRIVIAL = textwrap.dedent(
    """\
    syntax = "proto3";
    package acme.dedup;

    message Sample {
      string id = 1;
    }
    """
)


def _compile_to_descriptor_set(
    tmp_path: Path, sources: dict[str, str],
) -> Path:
    """Thin wrapper around the shared dedup helper.

    Pins a stable out_filename so failure messages keep field-
    behavior context. Behavior is identical to the shared helper
    otherwise. See :mod:`tests.schema.lint._cli_dedup_helpers` for
    the SSOT.
    """
    return compile_sources_to_descriptor_set(
        tmp_path, sources,
        out_filename="field_behavior_dedup.descriptor_set",
    )


def _invoke_lint_pack_dedup(descriptor_set: Path, *, profile: str):
    """Invoke ``protokit lint`` with a redundant ``--rule-pack`` flag.

    Centralizes the invocation shape so the two scenario tests
    below share one canonical argv. Passes ``catch_exceptions=False``
    per [[clirunner-catch-exceptions-false-explicit-discipline-2026-05-21]]
    so any unhandled exception in the CLI propagates with a real
    traceback rather than masking as ``exit_code=1`` + empty stdout.
    """
    return CliRunner().invoke(
        lint_main,
        [
            "--no-config",
            "--rule-pack=protokit.schema.lint.rules.options.field_behavior",
            "--profile", profile,
            str(descriptor_set),
        ],
        catch_exceptions=False,
    )


class TestFieldBehaviorPackExplicitLoadIsIdempotent:
    """``--rule-pack=...options.field_behavior`` is idempotent post-D6d U5.

    D6d U5 promotes ``options/field-behavior-consistent`` from
    dormant module-import to ``BUILTIN_PACKS`` membership. The
    promotion exercises the same coupled-mechanisms contract as
    D6b U7's ``package_same`` flip + D6c U2's ``package`` rule
    expansion — the test mirrors those patterns for the new
    BUILTIN_PACKS entry.

    The contract under test: explicit ``--rule-pack=`` for a pack
    already in ``BUILTIN_PACKS`` must NOT raise ``ValueError`` at
    the R25 multi-pack provenance line in ``cli.py``, regardless of
    whether the rule emits any findings.
    """

    def test_no_value_error_on_clean_fixture(
        self, tmp_path: Path,
    ) -> None:
        """Explicit redundant load does not raise ``ValueError``.

        The R25 multi-pack provenance line is evaluated whenever
        ``len(loaded_packs_tuple) >= 2``. With BUILTIN_PACKS now
        containing 8 packs post-D6d, the line ALWAYS fires when
        builtin rules are enabled (the default). A regression in
        CLI dedup would raise ``ValueError`` at zip strict-mode
        regardless of whether any rule found anything to flag.

        Asserts ``result.exception is None`` (per ce:review ADV-4)
        to guard against a future broad-except pattern that could
        absorb the ValueError + leave ``exit_code`` unaffected.
        """
        sources = {"sample.proto": _PROTO_TRIVIAL}
        descriptor_set = _compile_to_descriptor_set(tmp_path, sources)
        result = _invoke_lint_pack_dedup(
            descriptor_set, profile="default",
        )
        # No ValueError from zip(strict=True) at the R25 provenance
        # line. CliRunner with catch_exceptions=False propagates the
        # ValueError directly; the explicit None check also guards
        # against future broad-except masking.
        assert result.exception is None, (
            f"unexpected exception: {result.exception!r}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        # Clean fixture: no severity-bearing findings → exit 0.
        assert result.exit_code == 0, result.output

    def test_no_value_error_with_recommended_profile(
        self, tmp_path: Path,
    ) -> None:
        """Profile-filter does not affect the dedup mechanism.

        The ``recommended`` profile excludes
        ``options/field-behavior-consistent`` (which only ships in
        ``default``). Even with zero rules from the field_behavior
        pack participating in the composed profile, the pack is
        still in ``loaded_packs_tuple`` and the R25 provenance line
        iterates it via zip-strict. A CLI dedup regression would
        still surface ``ValueError``.
        """
        sources = {"sample.proto": _PROTO_TRIVIAL}
        descriptor_set = _compile_to_descriptor_set(tmp_path, sources)
        result = _invoke_lint_pack_dedup(
            descriptor_set, profile="recommended",
        )
        assert result.exception is None, (
            f"unexpected exception: {result.exception!r}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert result.exit_code == 0, result.output
