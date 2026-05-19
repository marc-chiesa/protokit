"""Tests for the D6c U2 R8 + R8b cross-file package-directory rules.

Covers the 2 rules added to :mod:`protokit.schema.lint.rules.package`
in D6c U2:

- ``package/same-directory`` (R8, buf:PACKAGE_SAME_DIRECTORY) — fires
  when a single package's files live in more than one directory.
- ``package/directory-same-package`` (R8b, buf:DIRECTORY_SAME_PACKAGE)
  — fires when a single directory contains files declaring more than
  one package. Has TWO message-template arms per buf empirical lock:

    - **Standard**: ``Multiple packages "X,Y[,Z]" detected within
      directory "<dir>".`` when all packages in the directory are
      declared (no packageless files mixed in).
    - **Empty-mixed**: ``Package "X" and file with no package
      detected within directory "<dir>".`` when the directory
      contains at least one declared-package file AND at least one
      packageless file. The single declared-package value rendered is
      alphabetically-first per protokit's deterministic-ordering
      convention; buf-empirical confirmed against the
      ``/tmp/d6c_phase0/empty_pkg/`` fixture.

Both rules consume the dual-view accumulator landed in D6c U1
(``LintEngine._build_directory_package_accumulator`` →
``FileLintContext.directory_packages`` + ``directory_packages_by_dir``).

Test fixtures use inline proto sources via the shared ``_compile`` +
``_run_single`` helpers (``tests/schema/lint/rules/conftest.py``).
Empirical-byte-parity against buf v1.69.0 is the parity gate's
responsibility (U3, ``tests/parity/test_parity_package_directory.py``);
this module pins the rule callables' semantics directly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from protokit.schema.lint.engine import LintEngine
from protokit.schema.lint.model import ElementKind, LintProfile, LintSeverity
from protokit.schema.lint.rules import package as package_pack
from protokit.schema.lint.rules.package import (
    RULES,
    check_directory_same_package,
    check_package_same_directory,
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


def _run_full_pack(
    tmp_path: Path,
    sources: dict[str, str],
    rule_ids: frozenset[str],
    min_severity: LintSeverity = LintSeverity.INFO,
) -> Any:
    """Run the engine with multiple rule_ids enabled from the package pack."""
    result = _compile(tmp_path, sources)
    engine = LintEngine()
    engine.load_rule_pack(package_pack)
    profile = LintProfile(
        name="_test_cofire",
        rule_ids=rule_ids,
        min_severity=min_severity,
    )
    return engine.run(result, profile=profile)


# ---------------------------------------------------------------------------
# Module shape — RULES tuple + spec metadata
# ---------------------------------------------------------------------------


class TestPackagePackShape:
    """The package pack exposes RULES with the 4 D6a + D6c rules registered."""

    def test_rules_tuple_contains_four_callables(self) -> None:
        assert isinstance(RULES, tuple)
        assert len(RULES) == 4
        for fn in RULES:
            assert hasattr(fn, "_lint_spec")

    def test_pack_includes_d6c_rules(self) -> None:
        assert check_package_same_directory in RULES
        assert check_directory_same_package in RULES


class TestR8RuleSpec:
    """``package/same-directory`` (R8) spec metadata."""

    def test_spec_metadata(self) -> None:
        spec = check_package_same_directory._lint_spec  # type: ignore[attr-defined]
        assert spec.rule_id == "package/same-directory"
        assert spec.severity is LintSeverity.ERROR
        assert spec.profiles == ("recommended", "default")
        assert spec.element is ElementKind.FILE
        assert spec.source_spec == "buf:PACKAGE_SAME_DIRECTORY"


class TestR8bRuleSpec:
    """``package/directory-same-package`` (R8b) spec metadata."""

    def test_spec_metadata(self) -> None:
        spec = check_directory_same_package._lint_spec  # type: ignore[attr-defined]
        assert spec.rule_id == "package/directory-same-package"
        assert spec.severity is LintSeverity.ERROR
        assert spec.profiles == ("recommended", "default")
        assert spec.element is ElementKind.FILE
        assert spec.source_spec == "buf:DIRECTORY_SAME_PACKAGE"


# ---------------------------------------------------------------------------
# R8 — package/same-directory
# ---------------------------------------------------------------------------


def _proto_pkg(package: str) -> str:
    """Generate an options-only proto-source declaring ``package``.

    proto3 accepts files with no messages — this matches the R7
    PACKAGE_SAME_* fixture style and avoids cross-file message-name
    collisions when multiple test files share a package. Files with
    no ``package`` declaration omit the line entirely (``package "";``
    is invalid proto3 syntax).
    """
    if package:
        return f'syntax = "proto3";\npackage {package};\n'
    return 'syntax = "proto3";\n'


_PROTO_PKG_FOO = _proto_pkg("acme.foo")
_PROTO_PKG_BAR = _proto_pkg("acme.bar")
_PROTO_NO_PKG = _proto_pkg("")


class TestR8HappyPath:
    """R8 fires on multi-directory single-package scenarios."""

    def test_split_package_across_two_dirs_fires_on_each(
        self, tmp_path: Path,
    ) -> None:
        """``acme.foo`` declared in ``dir1/a.proto`` + ``dir2/b.proto``.

        R8 emits one finding per root file (deterministic engine
        per-file walk). The directory-list payload is
        comma-no-space alphabetic per buf v1.69.0 empirical lock.
        """
        report = _run_single(
            tmp_path,
            {
                "dir1/a.proto": _PROTO_PKG_FOO,
                "dir2/b.proto": _PROTO_PKG_FOO,
            },
            "package/same-directory",
        )
        assert len(report.findings) == 2
        for f in report.findings:
            assert f.rule_id == "package/same-directory"
            assert f.violation_kind == "package/same-directory"
            assert f.params["package"] == "acme.foo"
            assert f.params["directories"] == "dir1,dir2"

    def test_split_package_n3_dirs_alphabetic_comma_no_space(
        self, tmp_path: Path,
    ) -> None:
        """3-directory split renders ``"d1,d2,d3"`` (comma-no-space, alpha sort).

        Empirically locked at /ce:plan time via /tmp/d6c_phase0/n3_dirs/.
        """
        report = _run_single(
            tmp_path,
            {
                "d3/a.proto": _PROTO_PKG_FOO,
                "d1/b.proto": _PROTO_PKG_FOO,
                "d2/c.proto": _PROTO_PKG_FOO,
            },
            "package/same-directory",
        )
        assert len(report.findings) == 3
        for f in report.findings:
            assert f.params["directories"] == "d1,d2,d3"
            assert f.params["package"] == "acme.foo"

    def test_proto_root_files_render_dot_directory(
        self, tmp_path: Path,
    ) -> None:
        """``acme.foo`` in proto-root + ``dir1/`` → directories include ``.``.

        Per KTD-4 (c) empirical lock — buf renders proto-root as ``"."``.
        Sort order: ``"."`` collates before alphabetic dirnames.
        """
        report = _run_single(
            tmp_path,
            {
                "a.proto": _PROTO_PKG_FOO,
                "dir1/b.proto": _PROTO_PKG_FOO,
            },
            "package/same-directory",
        )
        assert len(report.findings) == 2
        for f in report.findings:
            # ASCII-sorted: "." (0x2E) < "dir1" → ".,dir1"
            assert f.params["directories"] == ".,dir1"


class TestR8SilentCases:
    """R8 silent — package fits in one directory or has no fellow files."""

    def test_single_file_silent(self, tmp_path: Path) -> None:
        report = _run_single(
            tmp_path,
            {"dir1/a.proto": _PROTO_PKG_FOO},
            "package/same-directory",
        )
        assert report.findings == ()

    def test_same_dir_multiple_files_silent(self, tmp_path: Path) -> None:
        """Two files declaring same package in same dir — no split."""
        report = _run_single(
            tmp_path,
            {
                "dir1/a.proto": _PROTO_PKG_FOO,
                "dir1/b.proto": _PROTO_PKG_FOO,
            },
            "package/same-directory",
        )
        assert report.findings == ()

    def test_independent_packages_silent(self, tmp_path: Path) -> None:
        """Different packages in different dirs → no R8 fire on either."""
        report = _run_single(
            tmp_path,
            {
                "dir1/a.proto": _PROTO_PKG_FOO,
                "dir2/b.proto": _PROTO_PKG_BAR,
            },
            "package/same-directory",
        )
        assert report.findings == ()

    def test_packageless_files_skipped(self, tmp_path: Path) -> None:
        """R8 has no signal on empty-package files (R8b handles them)."""
        report = _run_single(
            tmp_path,
            {
                "dir1/a.proto": _PROTO_NO_PKG,
                "dir2/b.proto": _PROTO_NO_PKG,
            },
            "package/same-directory",
        )
        assert report.findings == ()


# ---------------------------------------------------------------------------
# R8b — package/directory-same-package
# ---------------------------------------------------------------------------


class TestR8bHappyPath:
    """R8b fires on multi-package single-directory scenarios."""

    def test_two_packages_in_same_dir_fires_on_each(
        self, tmp_path: Path,
    ) -> None:
        """``dir1`` contains ``acme.foo`` + ``acme.bar`` — both files fire.

        Standard message template: ``Multiple packages "X,Y" detected
        within directory "Z".`` with X,Y in alphabetic-sorted comma-no-
        space form.
        """
        report = _run_single(
            tmp_path,
            {
                "dir1/a.proto": _PROTO_PKG_FOO,
                "dir1/b.proto": _PROTO_PKG_BAR,
            },
            "package/directory-same-package",
        )
        assert len(report.findings) == 2
        for f in report.findings:
            assert f.rule_id == "package/directory-same-package"
            assert f.violation_kind == "package/directory-same-package"
            assert f.params["directory"] == "dir1"
            assert f.params["packages"] == "acme.bar,acme.foo"

    def test_three_packages_in_same_dir_alphabetic_comma_no_space(
        self, tmp_path: Path,
    ) -> None:
        """N=3 distinct packages in one dir → ``"acme.bar,acme.baz,acme.foo"``."""
        proto_baz = (
            'syntax = "proto3";\n'
            "package acme.baz;\n"
            "message Baz {}\n"
        )
        report = _run_single(
            tmp_path,
            {
                "dir1/a.proto": _PROTO_PKG_FOO,
                "dir1/b.proto": _PROTO_PKG_BAR,
                "dir1/c.proto": proto_baz,
            },
            "package/directory-same-package",
        )
        assert len(report.findings) == 3
        for f in report.findings:
            assert f.params["directory"] == "dir1"
            assert f.params["packages"] == "acme.bar,acme.baz,acme.foo"

    def test_proto_root_canonicalization(self, tmp_path: Path) -> None:
        """Files at proto-root render directory as ``"."`` per KTD-4 (c)."""
        report = _run_single(
            tmp_path,
            {
                "a.proto": _PROTO_PKG_FOO,
                "b.proto": _PROTO_PKG_BAR,
            },
            "package/directory-same-package",
        )
        assert len(report.findings) == 2
        for f in report.findings:
            assert f.params["directory"] == "."


class TestR8bEmptyMixedTemplate:
    """R8b empty-mixed arm — declared + packageless files in same dir.

    Per KTD-4 (b) empirical lock at ``/tmp/d6c_phase0/empty_pkg/``:
    buf fires R8b on packageless files mixed with declared-package files
    using a DISTINCT message template:
    ``Package "X" and file with no package detected within directory "Y".``
    """

    def test_empty_mixed_template_fires_on_all_files(
        self, tmp_path: Path,
    ) -> None:
        """1 declared + 2 packageless files in same dir → 3 findings each
        using the empty-mixed template."""
        report = _run_single(
            tmp_path,
            {
                "dir1/a.proto": _PROTO_PKG_FOO,
                "dir1/b.proto": _PROTO_NO_PKG,
                "dir1/c.proto": _PROTO_NO_PKG,
            },
            "package/directory-same-package",
        )
        assert len(report.findings) == 3
        for f in report.findings:
            assert f.rule_id == "package/directory-same-package"
            assert f.params["directory"] == "dir1"
            # Empty-mixed shape: single declared-pkg + flag indicating
            # the packageless arm was selected.
            assert f.params.get("packageless_present") is True
            assert f.params["package"] == "acme.foo"

    def test_empty_mixed_template_at_proto_root(
        self, tmp_path: Path,
    ) -> None:
        """1 declared + 1 packageless at proto-root → both fire empty-mixed."""
        report = _run_single(
            tmp_path,
            {
                "a.proto": _PROTO_PKG_FOO,
                "b.proto": _PROTO_NO_PKG,
            },
            "package/directory-same-package",
        )
        assert len(report.findings) == 2
        for f in report.findings:
            assert f.params["directory"] == "."
            assert f.params["package"] == "acme.foo"
            assert f.params.get("packageless_present") is True


class TestR8bSilentCases:
    """R8b silent — single package per dir."""

    def test_single_file_silent(self, tmp_path: Path) -> None:
        report = _run_single(
            tmp_path,
            {"dir1/a.proto": _PROTO_PKG_FOO},
            "package/directory-same-package",
        )
        assert report.findings == ()

    def test_same_package_in_same_dir_silent(self, tmp_path: Path) -> None:
        """Two files declaring same package in same dir → no R8b fire."""
        report = _run_single(
            tmp_path,
            {
                "dir1/a.proto": _PROTO_PKG_FOO,
                "dir1/b.proto": _PROTO_PKG_FOO,
            },
            "package/directory-same-package",
        )
        assert report.findings == ()

    def test_independent_dirs_silent(self, tmp_path: Path) -> None:
        """Different packages in different dirs → no R8b fire."""
        report = _run_single(
            tmp_path,
            {
                "dir1/a.proto": _PROTO_PKG_FOO,
                "dir2/b.proto": _PROTO_PKG_BAR,
            },
            "package/directory-same-package",
        )
        assert report.findings == ()

    def test_all_packageless_in_same_dir_silent(
        self, tmp_path: Path,
    ) -> None:
        """No declared-package file → empty-mixed arm doesn't trigger.

        The empty-mixed template fires when BOTH a declared package
        AND a packageless file co-occur. All-packageless directories
        produce ``directory_packages_by_dir[dir] = {"": {fnames}}`` —
        len == 1, so R8b is silent.
        """
        report = _run_single(
            tmp_path,
            {
                "dir1/a.proto": _PROTO_NO_PKG,
                "dir1/b.proto": _PROTO_NO_PKG,
            },
            "package/directory-same-package",
        )
        assert report.findings == ()


# ---------------------------------------------------------------------------
# R8 + R8b co-fire (KTD-9)
# ---------------------------------------------------------------------------


class TestCofireScenario:
    """R8 + R8b both fire on the canonical cofire fixture.

    Empirically locked at /tmp/d6c_phase0/cofire/: a 3-file fixture
    where ``pkg/a.proto`` (acme.foo) + ``pkg/b.proto`` (acme.bar) +
    ``other_dir/c.proto`` (acme.foo) produces:

    - R8 (PACKAGE_SAME_DIRECTORY): 2 findings (acme.foo split across
      ``pkg`` + ``other_dir``).
    - R8b (DIRECTORY_SAME_PACKAGE): 2 findings (``pkg`` contains
      acme.foo + acme.bar).
    - Total: 4 findings.

    The plan KTD-9 declares cofire ordering is rule_id-alphabetic
    (``package/directory-same-package`` < ``package/same-directory``),
    matching protokit's existing engine convention without special-case
    logic.
    """

    def test_cofire_fixture_produces_4_findings(
        self, tmp_path: Path,
    ) -> None:
        report = _run_full_pack(
            tmp_path,
            {
                "pkg/a.proto": _PROTO_PKG_FOO,
                "pkg/b.proto": _PROTO_PKG_BAR,
                "other_dir/c.proto": _PROTO_PKG_FOO,
            },
            frozenset({
                "package/same-directory",
                "package/directory-same-package",
            }),
        )
        # Pull the two rule families apart for the assertions.
        r8_findings = [
            f for f in report.findings
            if f.rule_id == "package/same-directory"
        ]
        r8b_findings = [
            f for f in report.findings
            if f.rule_id == "package/directory-same-package"
        ]
        # R8 fires on the 2 acme.foo files (pkg/a.proto + other_dir/c.proto)
        assert len(r8_findings) == 2
        r8_files = {f.params["file"] for f in r8_findings}
        assert r8_files == {"pkg/a.proto", "other_dir/c.proto"}
        # R8b fires on the 2 files in pkg/ (a + b)
        assert len(r8b_findings) == 2
        r8b_files = {f.params["file"] for f in r8b_findings}
        assert r8b_files == {"pkg/a.proto", "pkg/b.proto"}
        # Total findings.
        assert len(report.findings) == 4


# ---------------------------------------------------------------------------
# Severity demotion + per-rule disable
# ---------------------------------------------------------------------------


class TestSeverityOverride:
    """[severities] table demotes/disables R8 + R8b independently."""

    def test_r8_demoted_to_warning(self, tmp_path: Path) -> None:
        result = _compile(
            tmp_path,
            {
                "dir1/a.proto": _PROTO_PKG_FOO,
                "dir2/b.proto": _PROTO_PKG_FOO,
            },
        )
        engine = LintEngine()
        engine.load_rule_pack(package_pack)
        profile = LintProfile(
            name="_test",
            rule_ids=frozenset({"package/same-directory"}),
            min_severity=LintSeverity.INFO,
            rule_severity_overrides={
                "package/same-directory": LintSeverity.WARNING,
            },
        )
        report = engine.run(result, profile=profile)
        assert len(report.findings) == 2
        for f in report.findings:
            assert f.severity is LintSeverity.WARNING

    def test_r8b_silent_when_excluded_from_profile(
        self, tmp_path: Path,
    ) -> None:
        """A profile with only R8 in ``rule_ids`` does not fire R8b.

        Mirrors the de-facto disable path: ``[severities].rule_id = "off"``
        unloads the rule from the composed profile so it is not iterated
        in the engine's per-file walk. Here we exclude R8b directly from
        ``rule_ids`` to exercise the same observable contract.
        """
        result = _compile(
            tmp_path,
            {
                "dir1/a.proto": _PROTO_PKG_FOO,
                "dir1/b.proto": _PROTO_PKG_BAR,
            },
        )
        engine = LintEngine()
        engine.load_rule_pack(package_pack)
        profile = LintProfile(
            name="_test",
            rule_ids=frozenset({"package/same-directory"}),
            min_severity=LintSeverity.INFO,
        )
        report = engine.run(result, profile=profile)
        # R8 doesn't fire on a single-dir fixture; R8b is the only rule
        # that would fire on this fixture but we've excluded it.
        assert report.findings == ()


# ---------------------------------------------------------------------------
# Profile membership — R8 + R8b in recommended + default
# ---------------------------------------------------------------------------


_ALL_PACKAGE_RULE_IDS = frozenset(
    fn._lint_spec.rule_id  # type: ignore[attr-defined]
    for fn in RULES
)


class TestProfileMembership:
    """R8 + R8b ship in recommended + default, absent from essentials."""

    def test_recommended_contains_all_four_rules(self) -> None:
        profile = LintProfile.from_pack(package_pack, "recommended")
        assert "package/same-directory" in profile.rule_ids
        assert "package/directory-same-package" in profile.rule_ids
        assert profile.rule_ids == _ALL_PACKAGE_RULE_IDS

    def test_default_contains_all_four_rules(self) -> None:
        profile = LintProfile.from_pack(package_pack, "default")
        assert "package/same-directory" in profile.rule_ids
        assert "package/directory-same-package" in profile.rule_ids
        assert profile.rule_ids == _ALL_PACKAGE_RULE_IDS

    def test_essentials_excludes_r8_r8b(self) -> None:
        profile = LintProfile.from_pack(package_pack, "essentials")
        assert "package/same-directory" not in profile.rule_ids
        assert "package/directory-same-package" not in profile.rule_ids
