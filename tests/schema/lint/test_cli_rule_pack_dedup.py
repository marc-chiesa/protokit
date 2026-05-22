"""Parametrized CLI dedup regression for every BUILTIN_PACKS member.

**Promotion at the third near-copy-paste instance** (D6e U2 / PD-9):
this file consolidates the per-flip pattern that landed at
``test_cli_rule_pack_dedup_post_d6c.py`` (D6c) and
``test_cli_rule_pack_dedup_post_d6d.py`` (D6d). With D6e U1+U2
adding the ``field`` pack and U3 adding ``package/no-import-cycle``
to the existing ``package`` pack, the next per-flip file would
have been the third near-copy-paste. Per
[[shared-helper-third-instance-trigger]] (codified at U4 boundary
as ``near-copy-paste-third-instance-consolidation-trigger``), the
third near-copy-paste instance triggers promotion to a single
parametrized SSOT — this file replaces the two per-flip files +
the never-created post-D6e file.

The contract under test (same as the prior per-flip files):
``--rule-pack=<module>`` for any pack already in ``BUILTIN_PACKS``
must NOT raise ``ValueError`` at the R25 multi-pack provenance
line in ``cli.py`` (``zip(strict=True)`` mismatch between the
``loaded_packs`` list and the deduped ``_active_rule_ids_per_pack``
dict). The dedup is guarded by THREE coupled mechanisms:

1. **CLI-level dedup** at ``cli.py`` (around line 870, pre-R25
   provenance).
2. **Engine-level idempotent load** at
   ``engine.py:241-242``'s ``load_rule_pack`` short-circuit.
3. **Profile-level frozenset union** at ``model.py`` in
   ``LintProfile.compose``.

The test PARAMETRIZES over every BUILTIN_PACKS member at test-
module import time, so adding a new pack to BUILTIN_PACKS
automatically exercises this regression without a new test file.
Per-pack fixture overrides (``package`` needs multi-package
source for R8/R8b coverage; ``field`` needs proto2-required for
``field/not-required``) are encoded as per-case parametrize data.

Per [[clirunner-catch-exceptions-false-explicit-discipline-2026-05-21]]
every ``CliRunner.invoke`` passes ``catch_exceptions=False`` so
any unhandled exception in the CLI surfaces with a real traceback
rather than masking as ``exit_code=1`` + empty stdout.
"""

from __future__ import annotations

import textwrap
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest
from click.testing import CliRunner

from protokit.schema.lint.cli import main as lint_main
from protokit.schema.lint.rules import BUILTIN_PACKS
from tests.schema.lint._cli_dedup_helpers import (
    compile_sources_to_descriptor_set,
)

# ---------------------------------------------------------------------------
# Fixture proto sources
# ---------------------------------------------------------------------------

#: Clean fixture: proto3 stub with path-aligned filename (file
#: lives at ``acme/dedup/sample.proto`` matching package
#: ``acme.dedup``, so ``package/directory-match`` passes). Designed
#: to produce ZERO findings across every BUILTIN_PACKS member —
#: the dedup test is about ``ValueError`` prevention, not rule
#: firing, so a clean fixture is the cleanest signal.
_PROTO_TRIVIAL_PATH = "acme/dedup/sample.proto"
_PROTO_TRIVIAL_SOURCE = textwrap.dedent(
    """\
    syntax = "proto3";
    package acme.dedup;

    option go_package = "github.com/acme/dedup;dedup";
    option java_package = "com.acme.dedup";
    option csharp_namespace = "Acme.Dedup";
    option php_namespace = "Acme\\\\Dedup";
    option ruby_package = "Acme::Dedup";
    option swift_prefix = "AD";
    option java_multiple_files = true;

    message Sample {
      string id = 1;
    }
    """
)


# ---------------------------------------------------------------------------
# Per-pack parametrize-case configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _PackDedupCase:
    """One parametrize case: a pack + its dedup-test profile.

    Attributes:
        module_name: ``pack.__name__`` (e.g.,
            ``"protokit.schema.lint.rules.package"``).
        profile: ``--profile`` value passed to ``protokit lint``.

    The fixture sources are shared across every pack (one clean
    proto3 file at a path matching its package), so individual
    cases only vary by module + profile. Adding a new pack to
    BUILTIN_PACKS automatically lands a parametrize case via
    :func:`_build_cases`.
    """

    module_name: str
    profile: str


#: Per-pack profile overrides. Packs NOT listed here use ``default``.
#: ``field`` ships only in ``proto2-strict`` opt-in (D6e KD-5), so
#: the dedup test exercises that profile to verify the explicit-load
#: path is also idempotent for opt-in profiles.
_PER_PACK_PROFILE_OVERRIDES: dict[str, str] = {
    "protokit.schema.lint.rules.field": "proto2-strict",
}


def _build_cases() -> Sequence[_PackDedupCase]:
    """Walk BUILTIN_PACKS + apply per-pack profile overrides.

    Adding a new pack to BUILTIN_PACKS automatically lands a
    parametrize case here. Per-pack profile overrides live in
    :data:`_PER_PACK_PROFILE_OVERRIDES`.
    """
    cases: list[_PackDedupCase] = []
    for pack in BUILTIN_PACKS:
        module_name = pack.__name__
        profile = _PER_PACK_PROFILE_OVERRIDES.get(module_name, "default")
        cases.append(
            _PackDedupCase(module_name=module_name, profile=profile),
        )
    return tuple(cases)


_CASES: Sequence[_PackDedupCase] = _build_cases()


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


class TestRulePackDedupAcrossBuiltinPacks:
    """``--rule-pack=<module>`` is idempotent for every BUILTIN_PACKS pack.

    Replaces the per-flip files
    ``test_cli_rule_pack_dedup_post_d6c.py`` (D6c) and
    ``test_cli_rule_pack_dedup_post_d6d.py`` (D6d). The third
    near-copy-paste instance (the never-created post-D6e file)
    triggered the consolidation per the
    ``near-copy-paste-third-instance-consolidation-trigger``
    discipline.
    """

    @pytest.mark.parametrize(
        "case",
        _CASES,
        ids=[c.module_name.rsplit(".", 1)[-1] for c in _CASES],
    )
    def test_explicit_rule_pack_load_is_idempotent(
        self,
        case: _PackDedupCase,
        tmp_path: Path,
    ) -> None:
        """Explicit ``--rule-pack=<module>`` does NOT raise ValueError.

        The R25 multi-pack provenance line at ``cli.py`` is
        evaluated whenever ``len(loaded_packs_tuple) >= 2``. With
        BUILTIN_PACKS containing 9 packs post-D6e U1+U2, the line
        ALWAYS fires when builtin rules are enabled (the default).
        A regression in CLI dedup would raise ``ValueError`` at
        zip strict-mode regardless of whether any rule found
        anything to flag.

        Asserts ``result.exception is None`` (per ce:review ADV-4
        discipline at the D6d test) to guard against a future
        broad-except pattern that could absorb the ``ValueError``
        and leave ``exit_code`` unaffected.
        """
        descriptor_set = compile_sources_to_descriptor_set(
            tmp_path,
            {_PROTO_TRIVIAL_PATH: _PROTO_TRIVIAL_SOURCE},
            out_filename=(
                f"{case.module_name.rsplit('.', 1)[-1]}.descriptor_set"
            ),
        )
        result = CliRunner().invoke(
            lint_main,
            [
                "--no-config",
                f"--rule-pack={case.module_name}",
                "--profile",
                case.profile,
                str(descriptor_set),
            ],
            catch_exceptions=False,
        )
        # No ValueError from zip(strict=True) at the R25 provenance
        # line. catch_exceptions=False propagates any exception
        # directly; the explicit None check also guards against
        # future broad-except masking. Clean fixture: 0 findings →
        # exit 0 + exception None for every pack.
        assert result.exception is None, (
            f"unexpected exception for pack {case.module_name}: "
            f"{result.exception!r}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert result.exit_code == 0, (
            f"pack {case.module_name} with profile "
            f"{case.profile!r}: expected clean exit 0, "
            f"got {result.exit_code}.\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
