"""Tests for the D6a Unit 6 package-structural rule pack.

Covers the 2 rules registered in :mod:`protokit.schema.lint.rules.package`:

- ``package/defined`` — fires when a file has no ``package``
  declaration.
- ``package/directory-match`` — fires when the file's package
  segments don't match the file's directory path segments.

Patterns mirror ``tests/schema/lint/rules/test_imports.py``: shared
helpers from conftest, derived rule_id frozenset, per-rule TestClasses,
profile-membership tests, and a full-pack integration test.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from protokit.schema.lint.engine import LintEngine
from protokit.schema.lint.model import ElementKind, LintProfile, LintSeverity
from protokit.schema.lint.rules import package as package_pack
from protokit.schema.lint.rules.package import (
    RULES,
    check_package_defined,
    check_package_directory_match,
)

from .conftest import _compile
from .conftest import _run_single as _run_single_with_pack


def _run_single(
    tmp_path: Path,
    sources: dict[str, str],
    rule_id: str,
) -> Any:
    """Thin wrapper that fixes the pack to ``package`` for this file's tests."""
    return _run_single_with_pack(tmp_path, sources, rule_id, package_pack)


# ---------------------------------------------------------------------------
# Module shape — RULES tuple + spec metadata
# ---------------------------------------------------------------------------


class TestPackagePackShape:
    """The package pack exposes RULES with all D6a + D6c rules registered.

    D6a Unit 6 shipped 2 rules (``package/defined``,
    ``package/directory-match``). D6c U2 added 2 cross-file rules
    (``package/same-directory``, ``package/directory-same-package``).
    The detailed spec metadata + behavior for the D6c rules lives in
    :mod:`tests.schema.lint.rules.test_package_same_directory`; this
    class is the single source of truth for the pack-shape contract
    across both deliveries.
    """

    def test_rules_tuple_contains_five_callables(self) -> None:
        # D6e U3 (2026-05-22) added check_package_no_import_cycle
        # as the 5th rule in the package pack (the 26th buf BASIC
        # rule). Original count was 2 (D6a U6 package/defined +
        # package/directory-match), grown to 4 by D6c U2's
        # cross-file R8/R8b additions, now 5 with U3.
        assert isinstance(RULES, tuple)
        assert len(RULES) == 5
        for fn in RULES:
            assert hasattr(fn, "_lint_spec")

    def test_pack_includes_d6a_original_rules(self) -> None:
        assert check_package_defined in RULES
        assert check_package_directory_match in RULES


class TestPackageRuleSpecs:
    """The 2 new rules carry the D6a Unit 6 spec metadata."""

    def test_package_defined_spec(self) -> None:
        spec = check_package_defined._lint_spec  # type: ignore[attr-defined]
        assert spec.rule_id == "package/defined"
        assert spec.severity is LintSeverity.ERROR
        assert spec.profiles == ("recommended", "default")
        assert spec.element is ElementKind.FILE
        assert spec.source_spec == "buf:PACKAGE_DEFINED"

    def test_package_directory_match_spec(self) -> None:
        spec = check_package_directory_match._lint_spec  # type: ignore[attr-defined]
        assert spec.rule_id == "package/directory-match"
        assert spec.severity is LintSeverity.ERROR
        assert spec.profiles == ("recommended", "default")
        assert spec.element is ElementKind.FILE
        assert spec.source_spec == "buf:PACKAGE_DIRECTORY_MATCH"


# ---------------------------------------------------------------------------
# package/defined
# ---------------------------------------------------------------------------


_DEFINED_GOOD = """
syntax = "proto3";
package good;
message Good { string n = 1; }
"""

_DEFINED_BAD_NO_PACKAGE = """
syntax = "proto3";
message NoPkg { string n = 1; }
"""


class TestPackageDefined:
    """``package/defined`` fires on files without a ``package`` declaration."""

    def test_happy_path_package_declared_clean(self, tmp_path: Path) -> None:
        report = _run_single(
            tmp_path,
            {"good.proto": _DEFINED_GOOD},
            "package/defined",
        )
        assert report.findings == ()

    def test_sad_path_no_package_declaration_fires(
        self, tmp_path: Path,
    ) -> None:
        report = _run_single(
            tmp_path,
            {"nopkg.proto": _DEFINED_BAD_NO_PACKAGE},
            "package/defined",
        )
        assert len(report.findings) == 1
        f = report.findings[0]
        assert f.violation_kind == "package/defined"
        assert f.params == {"file": "nopkg.proto"}


# ---------------------------------------------------------------------------
# package/directory-match
# ---------------------------------------------------------------------------


_DIR_MATCH_GOOD = """
syntax = "proto3";
package acme.api.v1;
message Users { string name = 1; }
"""

_DIR_MATCH_BAD_MISMATCHED = """
syntax = "proto3";
package wrong.namespace;
message Users { string name = 1; }
"""

_DIR_MATCH_NO_PACKAGE_SKIPPED = """
syntax = "proto3";
message Users { string name = 1; }
"""

_DIR_MATCH_TOP_LEVEL_SKIPPED = """
syntax = "proto3";
package acme.api.v1;
message Users { string name = 1; }
"""


class TestPackageDirectoryMatch:
    """``package/directory-match`` fires when package segments don't match dir parts."""

    def test_happy_path_package_matches_directory_clean(
        self, tmp_path: Path,
    ) -> None:
        """``acme/api/v1/users.proto`` with ``package acme.api.v1;`` is clean."""
        report = _run_single(
            tmp_path,
            {"acme/api/v1/users.proto": _DIR_MATCH_GOOD},
            "package/directory-match",
        )
        assert report.findings == ()

    def test_sad_path_mismatched_package_fires(
        self, tmp_path: Path,
    ) -> None:
        """``acme/api/v1/users.proto`` with ``package wrong.namespace;`` fires."""
        report = _run_single(
            tmp_path,
            {"acme/api/v1/users.proto": _DIR_MATCH_BAD_MISMATCHED},
            "package/directory-match",
        )
        assert len(report.findings) == 1
        f = report.findings[0]
        assert f.violation_kind == "package/directory-match"
        assert f.params == {
            "file": "acme/api/v1/users.proto",
            "package": "wrong.namespace",
            "expected": "acme.api.v1",
        }

    def test_skipped_when_no_package_declared(
        self, tmp_path: Path,
    ) -> None:
        """A file with no ``package`` is skipped — that's ``package/defined``'s job.

        Both rules firing on the same root cause would double-count.
        ``package/directory-match`` defers to its sibling for the
        missing-package case.
        """
        report = _run_single(
            tmp_path,
            {"acme/api/v1/users.proto": _DIR_MATCH_NO_PACKAGE_SKIPPED},
            "package/directory-match",
        )
        assert report.findings == ()

    def test_skipped_when_file_is_top_level(
        self, tmp_path: Path,
    ) -> None:
        """A top-level file (no directory) has no directory to match against.

        Buf has the same behavior; the rule is intentionally
        directory-relative, so files at the descriptor pool's root
        are not subject to the match constraint.
        """
        report = _run_single(
            tmp_path,
            {"users.proto": _DIR_MATCH_TOP_LEVEL_SKIPPED},
            "package/directory-match",
        )
        assert report.findings == ()

    def test_single_segment_directory_match(self, tmp_path: Path) -> None:
        """``acme/users.proto`` with ``package acme;`` matches."""
        single_seg = """
syntax = "proto3";
package acme;
message U { string n = 1; }
"""
        report = _run_single(
            tmp_path,
            {"acme/users.proto": single_seg},
            "package/directory-match",
        )
        assert report.findings == ()

    def test_single_segment_directory_mismatch_fires(
        self, tmp_path: Path,
    ) -> None:
        """``acme/users.proto`` with ``package different;`` fires."""
        bad = """
syntax = "proto3";
package different;
message U { string n = 1; }
"""
        report = _run_single(
            tmp_path,
            {"acme/users.proto": bad},
            "package/directory-match",
        )
        assert len(report.findings) == 1
        assert report.findings[0].params == {
            "file": "acme/users.proto",
            "package": "different",
            "expected": "acme",
        }

    def test_package_more_segments_than_directory_fires(
        self, tmp_path: Path,
    ) -> None:
        """File at ``acme/v1/users.proto`` with ``package acme.v1.types;``
        fires — package has MORE segments than the directory path implies.
        """
        src = """
syntax = "proto3";
package acme.v1.types;
message U { string n = 1; }
"""
        report = _run_single(
            tmp_path,
            {"acme/v1/users.proto": src},
            "package/directory-match",
        )
        assert len(report.findings) == 1
        assert report.findings[0].params == {
            "file": "acme/v1/users.proto",
            "package": "acme.v1.types",
            "expected": "acme.v1",
        }

    def test_skipped_when_directory_part_is_not_valid_identifier(
        self, tmp_path: Path,
    ) -> None:
        """Directory parts that cannot form proto identifiers are skipped.

        The protobuf descriptor convention forbids leading-slash anchors,
        ``..`` segments, hyphens, and leading digits in package names.
        When the file path contains any of these in its directory parts,
        no meaningful "expected" package can be derived — the rule
        skips rather than emit a nonsense finding like
        ``expected="/.acme.v1"`` or ``expected="acme....v1"``. This
        defends against manually-constructed fixtures and synthesized
        descriptors that bypass the normalization the compile backends
        perform.

        Cannot easily construct these via compile_protos_to_result (the
        compiler rejects most of them), so this test exercises the
        guard via a manually-constructed FileDescriptorProto.
        """
        from google.protobuf import descriptor_pb2 as _pb2
        from google.protobuf import descriptor_pool as _pool

        for bad_name in ["/acme/v1/foo.proto", "acme/../v1/foo.proto"]:
            fdp = _pb2.FileDescriptorProto()
            fdp.name = bad_name
            fdp.syntax = "proto3"
            fdp.package = "should.not.match"
            pool = _pool.DescriptorPool()
            pool.Add(fdp)
            from protokit.schema.compile import CompileResult
            result = CompileResult(pool=pool, root_files=(bad_name,))
            engine = LintEngine()
            engine.load_rule_pack(package_pack)
            profile = LintProfile(
                name="t",
                rule_ids=frozenset({"package/directory-match"}),
                min_severity=LintSeverity.INFO,
            )
            report = engine.run(result, profile=profile)
            # Should skip cleanly without emitting findings.
            assert report.findings == (), (
                f"unexpected findings for {bad_name!r}: {report.findings}"
            )


# ---------------------------------------------------------------------------
# Profile membership — derived from RULES
# ---------------------------------------------------------------------------


_ALL_PACKAGE_RULE_IDS = frozenset(
    fn._lint_spec.rule_id  # type: ignore[attr-defined]
    for fn in RULES
)


class TestPackageProfileMembership:
    """``LintProfile.from_pack`` returns the expected rule_id sets."""

    def test_from_pack_recommended_contains_both_rules(self) -> None:
        profile = LintProfile.from_pack(package_pack, "recommended")
        assert profile.name == "recommended"
        assert profile.rule_ids == _ALL_PACKAGE_RULE_IDS

    def test_from_pack_default_contains_both_rules(self) -> None:
        profile = LintProfile.from_pack(package_pack, "default")
        assert profile.name == "default"
        assert profile.rule_ids == _ALL_PACKAGE_RULE_IDS

    def test_from_pack_essentials_contains_no_package_rules(self) -> None:
        profile = LintProfile.from_pack(package_pack, "essentials")
        assert profile.rule_ids == frozenset()

    def test_from_pack_unknown_profile_returns_empty(self) -> None:
        profile = LintProfile.from_pack(package_pack, "nonexistent")
        assert profile.rule_ids == frozenset()


# ---------------------------------------------------------------------------
# Integration — both rules fire on a deliberately-bad fixture
# ---------------------------------------------------------------------------


# A file with both violations: no package declaration AND located in
# a non-trivial directory path. package/defined fires (no package);
# package/directory-match SKIPS (defers to its sibling).
#
# The integration test below uses TWO files to exercise both rules:
# one missing-package file (fires package/defined) and one
# mismatched-package file (fires package/directory-match). The
# fixture demonstrates the rules are independent and that their
# skip-discipline (no double-counting) works under composition.
_NO_PKG_FIXTURE = """
syntax = "proto3";
message NoPkg { string n = 1; }
"""

_MISMATCH_FIXTURE = """
syntax = "proto3";
package wrong;
message M { string n = 1; }
"""


class TestPackagePackIntegration:
    """Both rules fire on a multi-file fixture that triggers each."""

    def test_recommended_profile_fires_both_package_rules(
        self, tmp_path: Path,
    ) -> None:
        result = _compile(
            tmp_path,
            {
                "nopkg.proto": _NO_PKG_FIXTURE,
                "acme/api/v1/mismatch.proto": _MISMATCH_FIXTURE,
            },
        )
        engine = LintEngine()
        engine.load_rule_pack(package_pack)
        profile = LintProfile.from_pack(package_pack, "recommended")
        report = engine.run(result, profile=profile)
        # Exactly 2 findings: package/defined on nopkg.proto +
        # package/directory-match on acme/api/v1/mismatch.proto.
        # (mismatch.proto has a package, so package/defined doesn't
        # fire on it; nopkg.proto has no package, so package/
        # directory-match skips it.)
        #
        # D6c U2 added R8 + R8b to the pack; this 2-file fixture has
        # neither a split-package nor a multi-package-dir layout, so
        # R8 + R8b stay silent — the integration test continues to
        # exercise the D6a-original 2-rule contract only.
        assert len(report.findings) == 2
        fired_rule_ids = {f.rule_id for f in report.findings}
        # Derive the D6a-original rule_ids from RULES so a future
        # rename of either D6a rule's rule_id propagates here without
        # an invisible update obligation (per
        # rule-pack-extension-ssot-rule-ids-and-test-class-naming-
        # 2026-05-12). The set is explicitly subsetted by callable
        # identity so future deliveries adding more rules to the
        # pack don't silently widen the expected rule_ids.
        d6a_package_rule_ids = frozenset(
            fn._lint_spec.rule_id  # type: ignore[attr-defined]
            for fn in (check_package_defined, check_package_directory_match)
        )
        assert fired_rule_ids == d6a_package_rule_ids
