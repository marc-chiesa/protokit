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

The contract under test has two complementary halves:

1. **No-ValueError contract** (parametrized over every BUILTIN_PACKS
   member): ``--rule-pack=<module>`` for any pack already in
   ``BUILTIN_PACKS`` must NOT raise ``ValueError`` at the R25
   multi-pack provenance line in ``cli.py`` (``zip(strict=True)``
   mismatch between the ``loaded_packs`` list and the deduped
   ``_active_rule_ids_per_pack`` dict). Uses a clean fixture that
   produces ZERO findings on every pack — exit_code==0 +
   exception is None is the assertion shape.

2. **Inflation-detection contract** (dedicated case for the
   ``package`` pack): re-introduced per ce:review P1 #1
   (2026-05-22). The original D6c per-flip test asserted
   ``len(r8_findings) == 2`` against a deliberately-dirty fixture
   to detect duplicate-pack-load finding INFLATION. Without an
   inflation assertion, a regression that double-emits findings
   (without raising ValueError) would slip through the no-error
   assertion. The dedicated test method below restores this
   coverage using :data:`_PROTO_PKG_DIRTY_SOURCES`.

The dedup is guarded by THREE coupled mechanisms:

1. **CLI-level dedup** at ``cli.py`` (around line 870, pre-R25
   provenance).
2. **Engine-level idempotent load** at
   ``engine.py:241-242``'s ``load_rule_pack`` short-circuit.
3. **Profile-level frozenset union** at ``model.py`` in
   ``LintProfile.compose``.

The no-ValueError contract PARAMETRIZES over every BUILTIN_PACKS
member at test-module import time, so adding a new pack to
BUILTIN_PACKS automatically exercises this regression without a
new test file. Per-pack profile overrides (``field`` ships under
``proto2-strict`` opt-in only) live in
:data:`_PER_PACK_PROFILE_OVERRIDES`.

Per [[clirunner-catch-exceptions-false-explicit-discipline-2026-05-21]]
every ``CliRunner.invoke`` passes ``catch_exceptions=False`` so
any unhandled exception in the CLI surfaces with a real traceback
rather than masking as ``exit_code=1`` + empty stdout.
"""

from __future__ import annotations

import json
import textwrap
from collections.abc import Mapping
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
#: the ValueError-prevention contract is the cleanest signal when
#: the fixture is hermetic.
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

#: Dirty multi-package fixture for the inflation-guard test case
#: (D6c U2 R8 + R8b coverage). ce:review P1 #1 (2026-05-22): the
#: original D6c per-flip test asserted ``len(r8_findings) == 2``
#: against this fixture to detect duplicate-pack-load finding
#: INFLATION. The clean-fixture-only consolidation lost that
#: signal — a regression that double-emits R8/R8b findings without
#: raising ValueError would slip through ``exit_code == 0``
#: assertions. The fixture below re-introduces the inflation
#: detector for the ``package`` pack as a second dedicated case.
_PROTO_PKG_FOO = textwrap.dedent(
    """\
    syntax = "proto3";
    package acme.foo;
    """
)
_PROTO_PKG_BAR = textwrap.dedent(
    """\
    syntax = "proto3";
    package acme.bar;
    """
)
_PROTO_PKG_DIRTY_SOURCES: dict[str, str] = {
    "pkg/a.proto": _PROTO_PKG_FOO,
    "pkg/b.proto": _PROTO_PKG_BAR,
    "other_dir/c.proto": _PROTO_PKG_FOO,
}


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

    The fixture sources for the always-on cases are shared across
    every pack (one clean proto3 file at a path matching its
    package), so individual cases only vary by module + profile.
    Adding a new pack to BUILTIN_PACKS automatically lands a
    parametrize case via :func:`_build_cases`. The R8/R8b
    inflation-guard test (per ce:review P1 #1) is a separate
    dedicated test method that uses :data:`_PROTO_PKG_DIRTY_SOURCES`.
    """

    module_name: str
    profile: str


#: Per-pack profile overrides. Packs NOT listed here use ``default``.
#: ``field`` ships only in ``proto2-strict`` opt-in (D6e KD-5), so
#: the dedup test exercises that profile to verify the explicit-load
#: path is also idempotent for opt-in profiles. Annotated as
#: ``Mapping`` (not ``dict``) per ce:review P2 #11 (kieran-python
#: KP-3): the lookup table is read-only by contract.
_PER_PACK_PROFILE_OVERRIDES: Mapping[str, str] = {
    "protokit.schema.lint.rules.field": "proto2-strict",
}


def _build_cases() -> tuple[_PackDedupCase, ...]:
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


_CASES: tuple[_PackDedupCase, ...] = _build_cases()


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

    def test_package_pack_r8_r8b_inflation_guard(
        self,
        tmp_path: Path,
    ) -> None:
        """R8/R8b finding counts do NOT inflate under explicit redundant load.

        ce:review P1 #1 (2026-05-22): restores the inflation-
        detection coverage from the deleted
        ``test_cli_rule_pack_dedup_post_d6c.py``. The clean-fixture-
        only parametrized cases assert ``exit_code == 0`` and
        ``exception is None`` — a regression that double-loads
        the package pack and double-emits R8/R8b findings (without
        raising ValueError) would slip through those assertions on
        a zero-findings fixture.

        This test uses a deliberately-dirty multi-package fixture
        that triggers BOTH R8 (``package/same-directory``: acme.foo
        split across ``pkg/`` and ``other_dir/``) and R8b
        (``package/directory-same-package``: ``pkg/`` contains both
        acme.foo and acme.bar). Each rule fires exactly one finding
        per root file. A duplicate-pack-load regression would
        inflate either count visibly.
        """
        descriptor_set = compile_sources_to_descriptor_set(
            tmp_path,
            _PROTO_PKG_DIRTY_SOURCES,
            out_filename="package_inflation_guard.descriptor_set",
        )
        result = CliRunner().invoke(
            lint_main,
            [
                "--no-config",
                "--rule-pack=protokit.schema.lint.rules.package",
                "--profile",
                "recommended",
                "--format",
                "json",
                str(descriptor_set),
            ],
            catch_exceptions=False,
        )
        # Exit 1 because R8 + R8b severities are ERROR; catch the
        # SystemExit(1) that CliRunner captures (catch_exceptions=
        # False propagates other exceptions but SystemExit is the
        # CLI's normal exit path).
        from click.exceptions import Exit as ClickExit
        assert isinstance(result.exception, (SystemExit, ClickExit)) or (
            result.exception is None
        ), (
            f"unexpected exception: {result.exception!r}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert result.exit_code == 1, (
            f"expected exit 1 (R8/R8b ERROR findings); "
            f"got {result.exit_code}.\nstdout={result.stdout!r}"
        )
        payload = json.loads(result.stdout)
        r8_findings = [
            f for f in payload["findings"]
            if f["rule_id"] == "package/same-directory"
        ]
        r8b_findings = [
            f for f in payload["findings"]
            if f["rule_id"] == "package/directory-same-package"
        ]
        # R8: acme.foo split between pkg/ + other_dir/ → 2 findings
        # (one per acme.foo root file). A duplicate-pack-load
        # would inflate to 4.
        assert len(r8_findings) == 2, (
            f"expected 2 R8 findings (one per acme.foo root file), "
            f"got {len(r8_findings)} — duplicate-pack-load would "
            f"inflate. findings={r8_findings!r}"
        )
        # R8b: pkg/ contains 2 packages → 2 findings (one per
        # file in pkg/). A duplicate-pack-load would inflate to 4.
        assert len(r8b_findings) == 2, (
            f"expected 2 R8b findings (one per pkg/ root file), "
            f"got {len(r8b_findings)} — duplicate-pack-load would "
            f"inflate. findings={r8b_findings!r}"
        )
