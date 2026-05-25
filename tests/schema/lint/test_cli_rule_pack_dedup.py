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


# ---------------------------------------------------------------------------
# D6f R14b: R9b flag interaction with CLI dedup machinery
# ---------------------------------------------------------------------------

#: Cross-pack dirty fixture for R14b: triggers ``naming/snake-case-fields``
#: (naming pack — ``BadField`` violates snake_case) AND ``package/defined``
#: (package pack — missing package declaration). Two findings from two
#: distinct packs gives R14b the cross-pack signal needed to verify
#: that a ``--disable-rule`` targeting one pack does NOT silently
#: suppress findings from the OTHER pack.
_PROTO_R14B_CROSS_PACK_PATH = "no_pkg.proto"
_PROTO_R14B_CROSS_PACK_SOURCE = textwrap.dedent(
    """\
    syntax = "proto3";
    // Intentionally no `package` declaration → package/defined fires.

    message Bad {
      string BadField = 1;  // naming/snake-case-fields fires
    }
    """
)


class TestR9bCliInteractionRegression:
    """D6f R14b — R9b flags interact cleanly with CLI dedup machinery.

    Separate from :class:`TestRulePackDedupAcrossBuiltinPacks` so a
    failing R14b case signals "R9b-specific issue", not "``--rule-pack``
    dedup". The parametrized-over-BUILTIN_PACKS scope of the sibling
    class is conceptually distinct from R9b-specific non-parametrized
    regression cases (per the D6f plan's scope-guardian F8 note).

    Coverage (5 cases):
        1. ``--disable-rule`` filters from BUILTIN_PACKS (the auto-
           loaded surface) — rule does not appear in findings.
        2. ``--enable-rule`` adds without duplication when the rule
           is already auto-loaded via BUILTIN_PACKS — rule fires
           exactly once per violation.
        3. Cross-pack-and-disable-rule interaction — ``--disable-rule``
           targeting pack A does NOT filter pack B's findings.
        4. Idempotent repeated ``--disable-rule R --disable-rule R``
           — no ``contradictory_disable_config`` warning (same
           polarity, no contradiction); rule disabled exactly once.
        5. Multi-kind ``custom/<suffix>`` prefix expansion via CLI
           — bare-prefix ``--disable-rule custom/<X>`` suppresses
           every materialized kind without duplication when the
           pyproject declares a multi-kind ``custom_annotation_rule``.
    """

    def test_disable_rule_filters_from_builtin_packs(
        self,
        tmp_path: Path,
    ) -> None:
        """Case 1: ``--disable-rule R`` filters R from BUILTIN_PACKS."""
        descriptor_set = compile_sources_to_descriptor_set(
            tmp_path,
            {_PROTO_R14B_CROSS_PACK_PATH: _PROTO_R14B_CROSS_PACK_SOURCE},
            out_filename="r14b_case1.descriptor_set",
        )
        result = CliRunner().invoke(
            lint_main,
            [
                "--no-config",
                "--profile", "default",
                "--format", "json",
                "--disable-rule", "naming/snake-case-fields",
                str(descriptor_set),
            ],
            catch_exceptions=False,
        )
        # SystemExit is the CLI's normal exit signal; the fixture
        # triggers package/defined (ERROR) so exit 1 is expected.
        # The R14b signal is the absence of naming/snake-case-fields
        # in the findings — independent of exit code.
        payload = json.loads(result.stdout)
        rule_ids = {f["rule_id"] for f in payload["findings"]}
        assert "naming/snake-case-fields" not in rule_ids, (
            "--disable-rule failed to filter naming/snake-case-fields "
            "from BUILTIN_PACKS — disable-rule directive did not "
            f"reach engine setup. findings={payload['findings']!r}"
        )

    def test_enable_rule_no_duplication_when_already_auto_loaded(
        self,
        tmp_path: Path,
    ) -> None:
        """Case 2: ``--enable-rule R`` on an already-auto-loaded R fires once.

        The rule is already in the default profile via BUILTIN_PACKS.
        ``--enable-rule`` is an additional enable directive on the
        same rule_id — the dedup machinery must NOT cause a
        double-emit. Exactly one ``naming/snake-case-fields`` finding
        is expected per ``BadField`` violation in the fixture.
        """
        descriptor_set = compile_sources_to_descriptor_set(
            tmp_path,
            {_PROTO_R14B_CROSS_PACK_PATH: _PROTO_R14B_CROSS_PACK_SOURCE},
            out_filename="r14b_case2.descriptor_set",
        )
        result = CliRunner().invoke(
            lint_main,
            [
                "--no-config",
                "--profile", "default",
                "--format", "json",
                "--enable-rule", "naming/snake-case-fields",
                str(descriptor_set),
            ],
            catch_exceptions=False,
        )
        # Exit 1 expected (package/defined ERROR + naming finding);
        # SystemExit is CLI's normal exit. The R14b signal is the
        # finding count for naming/snake-case-fields = exactly 1.
        payload = json.loads(result.stdout)
        naming_findings = [
            f
            for f in payload["findings"]
            if f["rule_id"] == "naming/snake-case-fields"
        ]
        # Exactly ONE naming finding (BadField). A duplicate-load
        # regression would inflate to 2.
        assert len(naming_findings) == 1, (
            f"expected 1 naming/snake-case-fields finding (BadField), "
            f"got {len(naming_findings)} — --enable-rule on an "
            f"already-auto-loaded rule must not duplicate. "
            f"findings={naming_findings!r}"
        )

    def test_cross_pack_disable_does_not_filter_other_pack_findings(
        self,
        tmp_path: Path,
    ) -> None:
        """Case 3: ``--disable-rule`` targeting pack A leaves pack B intact.

        Disabling ``naming/snake-case-fields`` (naming pack) must NOT
        suppress ``package/defined`` (package pack). The fixture
        triggers both rules; only the naming finding should drop.
        """
        descriptor_set = compile_sources_to_descriptor_set(
            tmp_path,
            {_PROTO_R14B_CROSS_PACK_PATH: _PROTO_R14B_CROSS_PACK_SOURCE},
            out_filename="r14b_case3.descriptor_set",
        )
        result = CliRunner().invoke(
            lint_main,
            [
                "--no-config",
                "--profile", "default",
                "--format", "json",
                "--disable-rule", "naming/snake-case-fields",
                str(descriptor_set),
            ],
            catch_exceptions=False,
        )
        # Exit 1 expected (package/defined ERROR survives the
        # naming-only disable). SystemExit is CLI's normal exit.
        payload = json.loads(result.stdout)
        rule_ids = {f["rule_id"] for f in payload["findings"]}
        assert "naming/snake-case-fields" not in rule_ids, (
            "disable-rule did not filter naming/snake-case-fields"
        )
        # The package/defined finding from the OTHER pack must still
        # appear — disable must not leak across pack boundaries.
        assert "package/defined" in rule_ids, (
            "disable-rule on naming pack incorrectly suppressed "
            "package/defined (a different pack's finding). "
            f"findings={payload['findings']!r}"
        )

    def test_repeated_disable_rule_is_idempotent_no_contradiction(
        self,
        tmp_path: Path,
    ) -> None:
        """Case 4: ``--disable-rule R --disable-rule R`` is idempotent.

        Same polarity (both disable), same rule_id → no contradiction.
        Must NOT emit a ``contradictory_disable_config`` runtime
        warning (which would falsely signal a user error on a
        legitimate, idempotent duplicate directive). Rule disabled
        exactly once.
        """
        descriptor_set = compile_sources_to_descriptor_set(
            tmp_path,
            {_PROTO_R14B_CROSS_PACK_PATH: _PROTO_R14B_CROSS_PACK_SOURCE},
            out_filename="r14b_case4.descriptor_set",
        )
        result = CliRunner().invoke(
            lint_main,
            [
                "--no-config",
                "--profile", "default",
                "--format", "json",
                "--disable-rule", "naming/snake-case-fields",
                "--disable-rule", "naming/snake-case-fields",
                str(descriptor_set),
            ],
            catch_exceptions=False,
        )
        # Exit 1 expected (package/defined ERROR). SystemExit is
        # CLI's normal exit. The R14b signal is the absence of
        # contradictory_disable_config (idempotent dedup) AND the
        # rule_id missing from findings.
        payload = json.loads(result.stdout)
        # Disable wins; rule_id absent from findings.
        rule_ids = {f["rule_id"] for f in payload["findings"]}
        assert "naming/snake-case-fields" not in rule_ids
        # No false-positive contradiction warning. Disable + disable
        # on the same rule_id is idempotent (same polarity).
        contradictory = [
            w
            for w in payload["runtime_warnings"]
            if w["category"] == "contradictory_disable_config"
        ]
        assert contradictory == [], (
            "repeated --disable-rule on the same rule_id is "
            "idempotent (same polarity); no "
            "contradictory_disable_config warning should fire. "
            f"got: {contradictory!r}"
        )

    def test_multi_kind_custom_prefix_expansion_via_cli_no_duplication(
        self,
        tmp_path: Path,
    ) -> None:
        """Case 5: bare ``custom/<suffix>`` disable suppresses ALL materialized kinds.

        Two-part verification (ce:review F#4 rewrite, 2026-05-25):

        Part 1 — **unit-level prefix-expansion pin** via
        ``ResolvedLintConfig.from_dict``. A multi-kind spec
        (``element_kinds = ["method", "field"]``) produces two
        materialized rule_ids: ``custom/dual-thing`` (first kind,
        bare) + ``custom/dual-thing__field`` (subsequent kind,
        mangled per ``synthetic_rule_ids``). Bare-prefix
        ``disabled_rules = ["custom/dual-thing"]`` MUST expand at
        the config-resolution layer to suppress BOTH. This is the
        load-bearing prefix-expansion assertion.

        Part 2 — **CLI baseline-vs-disable comparison** using a real
        extension defined on ``MethodOptions``. Without disable,
        the ``METHOD`` closure fires a finding (annotation absent)
        AND the ``FIELD`` closure emits ``rule_exception`` warnings
        (``HasExtension`` raises ``KeyError`` because
        ``example.dual_thing`` extends ``MethodOptions``, not
        ``FieldOptions``). With bare-prefix
        ``--disable-rule custom/dual-thing``, BOTH closures are
        unloaded — the finding disappears AND the rule_exception
        warnings for ``custom/dual-thing__field`` disappear.
        Comparing both observables before/after rules out the prior
        false-confidence design where the test passed regardless of
        whether the second kind was actually suppressed.
        """
        # Part 1 — unit-level prefix-expansion pin.
        from protokit.schema.lint._config import ResolvedLintConfig

        resolved = ResolvedLintConfig.from_dict(
            {
                "custom_annotation_rules": [
                    {
                        "rule_suffix": "dual-thing",
                        "option": "example.dual_thing",
                        "element_kinds": ["method", "field"],
                        "severity": "warning",
                    },
                ],
                "disabled_rules": ["custom/dual-thing"],
            },
            {},
        )
        assert "custom/dual-thing" in resolved.disabled_rules, (
            "bare-prefix custom/dual-thing did not survive config "
            f"resolution: {resolved.disabled_rules!r}"
        )
        assert "custom/dual-thing__field" in resolved.disabled_rules, (
            "bare-prefix custom/dual-thing did not expand to the "
            "subsequent-kind mangled form custom/dual-thing__field. "
            f"resolved disabled_rules: {resolved.disabled_rules!r}"
        )

        # Part 2 — CLI baseline-vs-disable comparison.
        # Extension declared on MethodOptions only — the METHOD
        # closure resolves and fires; the FIELD closure hits KeyError
        # and emits custom_annotation_extension_unresolved. Both
        # observables drop to zero under the bare-prefix disable.
        ext_proto = textwrap.dedent(
            """\
            syntax = "proto2";
            package example;
            import "google/protobuf/descriptor.proto";
            extend google.protobuf.MethodOptions {
              optional string dual_thing = 50001;
            }
            """
        )
        svc_proto = textwrap.dedent(
            """\
            syntax = "proto3";
            package r14b.dual;
            message Carrier { string id = 1; }
            service Carriers {
              rpc Get(Carrier) returns (Carrier);
            }
            """
        )
        descriptor_set = compile_sources_to_descriptor_set(
            tmp_path,
            {
                "example/dual_thing.proto": ext_proto,
                "r14b/dual/carrier.proto": svc_proto,
            },
            out_filename="r14b_case5.descriptor_set",
        )
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            textwrap.dedent(
                """\
                [tool.protokit.lint]
                profile = "default"

                [[tool.protokit.lint.custom_annotation_rules]]
                rule_suffix    = "dual-thing"
                option         = "example.dual_thing"
                element_kinds  = ["method", "field"]
                severity       = "warning"
                """,
            ),
            encoding="utf-8",
        )

        # Baseline: NO --disable-rule. Verify both closures registered:
        # METHOD fires a finding; FIELD fires an unresolved warning.
        baseline = CliRunner().invoke(
            lint_main,
            [
                f"--config={pyproject}",
                "--format", "json",
                str(descriptor_set),
            ],
            catch_exceptions=False,
        )
        baseline_payload = json.loads(baseline.stdout)
        baseline_method_findings = [
            f
            for f in baseline_payload["findings"]
            if f["rule_id"] == "custom/dual-thing"
        ]
        baseline_field_rule_exceptions = [
            w
            for w in baseline_payload["runtime_warnings"]
            if w["category"] == "rule_exception"
            and w["rule_id"] == "custom/dual-thing__field"
        ]
        assert len(baseline_method_findings) >= 1, (
            "baseline must fire at least one custom/dual-thing finding "
            "(absent annotation on Carriers.Get method); without this "
            "signal the disable assertion below is vacuous. "
            f"findings={baseline_payload['findings']!r}"
        )
        assert len(baseline_field_rule_exceptions) >= 1, (
            "baseline must fire at least one rule_exception warning for "
            "custom/dual-thing__field (FIELD kind closure raises KeyError "
            "because example.dual_thing extends MethodOptions, not "
            "FieldOptions); without this signal the disable assertion "
            f"below is vacuous. warnings={baseline_payload['runtime_warnings']!r}"
        )

        # Disable: --disable-rule custom/dual-thing (bare). Both
        # materialized rule_ids should be unloaded → method finding
        # disappears AND field unresolved warning disappears.
        result = CliRunner().invoke(
            lint_main,
            [
                f"--config={pyproject}",
                "--format", "json",
                "--disable-rule", "custom/dual-thing",
                str(descriptor_set),
            ],
            catch_exceptions=False,
        )
        payload = json.loads(result.stdout)
        surviving_custom_findings = [
            f
            for f in payload["findings"]
            if f["rule_id"].startswith("custom/")
        ]
        surviving_custom_warnings = [
            w
            for w in payload["runtime_warnings"]
            if w["category"] == "rule_exception"
            and (w["rule_id"] or "").startswith("custom/")
        ]
        assert surviving_custom_findings == [], (
            "bare-prefix --disable-rule custom/dual-thing failed to "
            "suppress the METHOD closure (rule_id custom/dual-thing). "
            f"Surviving findings: {surviving_custom_findings!r}"
        )
        assert surviving_custom_warnings == [], (
            "bare-prefix --disable-rule custom/dual-thing failed to "
            "suppress the FIELD closure (rule_id custom/dual-thing__field) "
            "— the field-kind closure still ran and emitted rule_exception "
            "warnings. This is exactly the regression scenario the prior "
            f"test design could not catch. Surviving warnings: "
            f"{surviving_custom_warnings!r}"
        )
