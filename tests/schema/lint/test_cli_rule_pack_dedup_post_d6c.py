"""CLI dedup regression test for ``--rule-pack=...package`` post-D6c U2.

Background: D6b U7 surfaced a bug at the BUILTIN_PACKS-flip of
``package_same`` where invoking ``protokit lint --rule-pack=
protokit.schema.lint.rules.package_same`` raised
``ValueError('zip() argument 2 is shorter than argument 1')`` at
``cli.py:998-999``'s R25 multi-pack provenance line, because the CLI
loaded_packs list grew a duplicate entry while the
``_active_rule_ids_per_pack`` helper dict was keyed by
``pack.__name__`` (i.e., deduped). The fix added the load-bearing
CLI-level dedup at ``cli.py:841-846``.

D6c U2 adds R8 + R8b to the ``package`` pack. ``package`` was
already in ``BUILTIN_PACKS`` pre-D6c, but the pack's rule_ids grew
from 2 to 4 — exercising a different code path than the U7 flip.
This regression test mirrors
:class:`TestRulePackExplicitLoadIsIdempotent` for the ``package``
pack, verifying the THREE coupled mechanisms still hold:

1. **CLI-level dedup at** ``cli.py:841-846``.
2. **Engine-level idempotent load** at ``engine.py:241-242``.
3. **Profile-level frozenset union** at ``model.py:717-719``.

Without any of these, ``--rule-pack=protokit.schema.lint.rules.package``
on an R8/R8b fixture would either raise the zip-strict ValueError
or double-emit findings.
"""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from protokit.schema.lint.cli import main as lint_main
from tests.schema.lint._cli_dedup_helpers import (
    compile_sources_to_descriptor_set,
)

_PROTO_PKG_FOO = (
    'syntax = "proto3";\n'
    "package acme.foo;\n"
)

_PROTO_PKG_BAR = (
    'syntax = "proto3";\n'
    "package acme.bar;\n"
)


def _compile_to_descriptor_set(
    tmp_path: Path, sources: dict[str, str],
) -> Path:
    """Thin wrapper around the shared dedup helper.

    Pins the per-file output name (``package.descriptor_set``) for
    this test file so failure messages keep the package-pack
    context. Behavior is identical to the shared helper otherwise.
    See :mod:`tests.schema.lint._cli_dedup_helpers` for the SSOT.
    """
    return compile_sources_to_descriptor_set(
        tmp_path, sources, out_filename="package.descriptor_set",
    )


class TestPackagePackExplicitLoadIsIdempotent:
    """``--rule-pack=...package`` is idempotent post-D6c U2.

    D6c U2 grows the ``package`` pack from 2 rules (D6a) to 4 rules
    (R8 + R8b added). The pack is in ``BUILTIN_PACKS``, so an
    explicit ``--rule-pack`` for it is a redundant load — the
    coupled CLI dedup + engine short-circuit + profile-frozenset-
    union mechanisms must keep the contract.
    """

    def test_descriptor_set_mode_recommended_profile(
        self, tmp_path: Path,
    ) -> None:
        """Idempotent load + R8 + R8b fire + no ValueError at zip(strict=True).

        Cofire fixture: ``pkg/a.proto`` (acme.foo) + ``pkg/b.proto``
        (acme.bar) + ``other_dir/c.proto`` (acme.foo) — triggers BOTH
        R8 (acme.foo split across 2 dirs) and R8b (``pkg`` contains 2
        packages). Each rule fires one finding per root file, so a
        duplicate-pack-load regression would inflate the count visibly
        on either rule independently. Exit code is 1 (ERROR severity).
        """
        sources = {
            "pkg/a.proto": _PROTO_PKG_FOO,
            "pkg/b.proto": _PROTO_PKG_BAR,
            "other_dir/c.proto": _PROTO_PKG_FOO,
        }
        descriptor_set = _compile_to_descriptor_set(tmp_path, sources)
        result = CliRunner().invoke(
            lint_main,
            [
                "--no-config",
                "--rule-pack=protokit.schema.lint.rules.package",
                "--profile", "recommended",
                "--format", "json",
                str(descriptor_set),
            ],
        )
        # Exit 1 because R8 + R8b severities are ERROR (R20 ladder).
        # Critically: no ValueError from zip(strict=True) at cli.py:998-999.
        assert result.exit_code == 1, result.output
        payload = json.loads(result.stdout)
        r8_findings = [
            f for f in payload["findings"]
            if f["rule_id"] == "package/same-directory"
        ]
        r8b_findings = [
            f for f in payload["findings"]
            if f["rule_id"] == "package/directory-same-package"
        ]
        # R8: acme.foo split between pkg/ + other_dir/ → 2 findings.
        assert len(r8_findings) == 2, (
            f"expected 2 R8 findings (one per acme.foo root file), "
            f"got {len(r8_findings)} — duplicate-load would inflate"
        )
        # R8b: pkg/ has 2 packages → 2 findings (one per file in pkg/).
        assert len(r8b_findings) == 2, (
            f"expected 2 R8b findings (one per pkg/ root file), "
            f"got {len(r8b_findings)} — duplicate-load would inflate"
        )

    def test_descriptor_set_mode_default_profile(
        self, tmp_path: Path,
    ) -> None:
        """Idempotent load also under the ``default`` profile."""
        sources = {
            "pkg/a.proto": _PROTO_PKG_FOO,
            "pkg/b.proto": _PROTO_PKG_BAR,
            "other_dir/c.proto": _PROTO_PKG_FOO,
        }
        descriptor_set = _compile_to_descriptor_set(tmp_path, sources)
        result = CliRunner().invoke(
            lint_main,
            [
                "--no-config",
                "--rule-pack=protokit.schema.lint.rules.package",
                "--profile", "default",
                "--format", "json",
                str(descriptor_set),
            ],
        )
        assert result.exit_code == 1, result.output
        payload = json.loads(result.stdout)
        r8_findings = [
            f for f in payload["findings"]
            if f["rule_id"] == "package/same-directory"
        ]
        r8b_findings = [
            f for f in payload["findings"]
            if f["rule_id"] == "package/directory-same-package"
        ]
        assert len(r8_findings) == 2
        assert len(r8b_findings) == 2

    def test_no_value_error_on_clean_fixture(
        self, tmp_path: Path,
    ) -> None:
        """Even with no findings, explicit redundant load does not raise.

        The R25 multi-pack provenance line at ``cli.py:998-999`` is
        evaluated whenever ``len(loaded_packs_tuple) >= 2``. A single
        file with a single package + a clean directory layout produces
        zero R8/R8b findings — but the provenance line still runs over
        the now-deduped pack list. A regression in CLI dedup would
        raise ``ValueError`` at zip strict-mode regardless of findings.
        """
        sources = {"a.proto": _PROTO_PKG_FOO}
        descriptor_set = _compile_to_descriptor_set(tmp_path, sources)
        result = CliRunner().invoke(
            lint_main,
            [
                "--no-config",
                "--rule-pack=protokit.schema.lint.rules.package",
                "--profile", "recommended",
                str(descriptor_set),
            ],
        )
        # Clean fixture: no findings means exit 0.
        assert result.exit_code == 0, result.output
