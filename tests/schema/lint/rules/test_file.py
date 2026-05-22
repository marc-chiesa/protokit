"""Tests for the D6a Unit 6 file-structural rule pack.

Covers the 1 rule registered in :mod:`protokit.schema.lint.rules.file`:

- ``file/syntax-specified`` — fires (at **WARNING** as of D6e R4b)
  when the file's resolved syntax is not ``"proto3"`` or
  ``"editions"``. **Documented buf-parity divergence**: protokit's
  rule fires on both no-syntax files AND explicit
  ``syntax = "proto2";`` files, because the protobuf compiler
  emits ``fdp.syntax == ""`` for both cases (the field is only
  set for non-default syntax). Buf's rule, by contrast, is
  source-aware and fires only on the no-syntax case. The tests
  below pin both branches to document the divergence and to keep
  it CI-enforced. D6e R4b demoted the default severity from
  ERROR to WARNING under the inverted UX philosophy (D6e KD-2:
  pragmatic-not-dogmatic about proto2); proto3-only shops can
  re-promote to ERROR via ``[tool.protokit.lint.severities]``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from protokit.schema.lint.engine import LintEngine
from protokit.schema.lint.model import ElementKind, LintProfile, LintSeverity
from protokit.schema.lint.rules import file as file_pack
from protokit.schema.lint.rules.file import (
    RULES,
    check_syntax_specified,
)

from .conftest import _compile
from .conftest import _run_single as _run_single_with_pack


def _run_single(
    tmp_path: Path,
    sources: dict[str, str],
    rule_id: str,
) -> Any:
    """Thin wrapper that fixes the pack to ``file`` for this file's tests."""
    return _run_single_with_pack(tmp_path, sources, rule_id, file_pack)


# ---------------------------------------------------------------------------
# Module shape — RULES tuple + spec metadata
# ---------------------------------------------------------------------------


class TestFilePackShape:
    """The file pack exposes RULES with the D6a Unit 6 rule registered."""

    def test_rules_tuple_contains_one_callable(self) -> None:
        assert isinstance(RULES, tuple)
        assert len(RULES) == 1
        for fn in RULES:
            assert hasattr(fn, "_lint_spec")

    def test_pack_includes_the_rule(self) -> None:
        assert check_syntax_specified in RULES


class TestFileRuleSpecs:
    """The new rule carries the D6a Unit 6 spec metadata."""

    def test_syntax_specified_spec(self) -> None:
        spec = check_syntax_specified._lint_spec  # type: ignore[attr-defined]
        assert spec.rule_id == "file/syntax-specified"
        # D6e R4b demotion: ERROR -> WARNING in recommended + default
        # profiles. Re-promote via [severities] override if needed.
        assert spec.severity is LintSeverity.WARNING
        assert spec.profiles == ("recommended", "default")
        assert spec.element is ElementKind.FILE
        assert spec.source_spec == "buf:SYNTAX_SPECIFIED"


# ---------------------------------------------------------------------------
# file/syntax-specified
# ---------------------------------------------------------------------------


_SYNTAX_PROTO3 = """
syntax = "proto3";
package good;
message Good { string n = 1; }
"""

_SYNTAX_EXPLICIT_PROTO2 = """
syntax = "proto2";
package p2;
message P2 { optional string n = 1; }
"""

# No syntax statement at all — protobuf defaults to proto2 silently.
_SYNTAX_NO_STATEMENT = """
package implicit;
message Implicit { optional string n = 1; }
"""


class TestSyntaxSpecified:
    """``file/syntax-specified`` fires on every non-proto3 file."""

    def test_happy_path_proto3_explicit_clean(self, tmp_path: Path) -> None:
        report = _run_single(
            tmp_path,
            {"good.proto": _SYNTAX_PROTO3},
            "file/syntax-specified",
        )
        assert report.findings == ()

    def test_sad_path_explicit_proto2_fires(
        self, tmp_path: Path,
    ) -> None:
        """Explicit ``syntax = "proto2";`` fires.

        This diverges from buf's SYNTAX_SPECIFIED behavior (which
        would not fire because the syntax IS specified). The
        divergence is unavoidable: the protobuf compiler emits
        ``fdp.syntax == ""`` for explicit proto2 files (the field
        is only set for non-default syntax), so the descriptor
        cannot distinguish "explicit proto2" from "no syntax
        statement". Protokit chooses the stricter posture —
        nudging toward proto3 — and accepts the divergence as
        documented in the rule docstring.
        """
        report = _run_single(
            tmp_path,
            {"p2.proto": _SYNTAX_EXPLICIT_PROTO2},
            "file/syntax-specified",
        )
        assert len(report.findings) == 1
        f = report.findings[0]
        assert f.violation_kind == "file/syntax-specified"
        assert f.params == {"file": "p2.proto"}

    def test_sad_path_no_syntax_statement_fires(
        self, tmp_path: Path,
    ) -> None:
        """No syntax statement (implicit proto2) fires.

        This is the case buf's SYNTAX_SPECIFIED was designed to
        catch. Protokit's rule matches buf on this branch.
        """
        report = _run_single(
            tmp_path,
            {"implicit.proto": _SYNTAX_NO_STATEMENT},
            "file/syntax-specified",
        )
        assert len(report.findings) == 1
        f = report.findings[0]
        assert f.violation_kind == "file/syntax-specified"
        assert f.params == {"file": "implicit.proto"}

    def test_happy_path_editions_clean(self) -> None:
        """Proto-editions files (``fdp.syntax == "editions"``) are clean.

        The rule's spirit is "did the user opt into a non-default
        syntax". Editions IS an explicit opt-in, so the rule treats
        it as clean. The ``_CLEAN_SYNTAXES`` frozenset documents
        the accepted values; this test pins the editions branch
        before editions adoption arrives in earnest.

        Cannot construct an editions file via the test-fixture
        compile path (the project's compile backends don't
        support editions yet), so this test exercises the
        ``_CLEAN_SYNTAXES`` membership via a manually-constructed
        FileDescriptorProto with ``syntax = "editions"`` and
        ``edition = EDITION_2023``.
        """
        from google.protobuf import descriptor_pb2 as _pb2
        from google.protobuf import descriptor_pool as _pool

        fdp = _pb2.FileDescriptorProto()
        fdp.name = "ed.proto"
        fdp.syntax = "editions"
        fdp.edition = _pb2.Edition.EDITION_2023
        fdp.package = "ed"
        pool = _pool.DescriptorPool()
        pool.Add(fdp)
        from protokit.schema.compile import CompileResult
        result = CompileResult(pool=pool, root_files=("ed.proto",))
        engine = LintEngine()
        engine.load_rule_pack(file_pack)
        profile = LintProfile(
            name="t",
            rule_ids=frozenset({"file/syntax-specified"}),
            min_severity=LintSeverity.INFO,
        )
        report = engine.run(result, profile=profile)
        assert report.findings == ()


# ---------------------------------------------------------------------------
# Profile membership — derived from RULES
# ---------------------------------------------------------------------------


_ALL_FILE_RULE_IDS = frozenset(
    fn._lint_spec.rule_id  # type: ignore[attr-defined]
    for fn in RULES
)


class TestFileProfileMembership:
    """``LintProfile.from_pack`` returns the expected rule_id sets."""

    def test_from_pack_recommended_contains_the_rule(self) -> None:
        profile = LintProfile.from_pack(file_pack, "recommended")
        assert profile.name == "recommended"
        assert profile.rule_ids == _ALL_FILE_RULE_IDS

    def test_from_pack_default_contains_the_rule(self) -> None:
        profile = LintProfile.from_pack(file_pack, "default")
        assert profile.name == "default"
        assert profile.rule_ids == _ALL_FILE_RULE_IDS

    def test_from_pack_essentials_contains_no_file_rules(self) -> None:
        profile = LintProfile.from_pack(file_pack, "essentials")
        assert profile.rule_ids == frozenset()

    def test_from_pack_unknown_profile_returns_empty(self) -> None:
        profile = LintProfile.from_pack(file_pack, "nonexistent")
        assert profile.rule_ids == frozenset()


# ---------------------------------------------------------------------------
# Integration — the rule fires on a deliberately-bad fixture
# ---------------------------------------------------------------------------


class TestFilePackIntegration:
    """The rule fires on a non-proto3 file under the recommended profile."""

    def test_recommended_profile_fires_on_proto2(
        self, tmp_path: Path,
    ) -> None:
        result = _compile(
            tmp_path,
            {"p2.proto": _SYNTAX_EXPLICIT_PROTO2},
        )
        engine = LintEngine()
        engine.load_rule_pack(file_pack)
        profile = LintProfile.from_pack(file_pack, "recommended")
        report = engine.run(result, profile=profile)
        assert len(report.findings) == 1
        assert report.findings[0].rule_id == "file/syntax-specified"

    def test_recommended_profile_emits_warning_not_error(
        self, tmp_path: Path,
    ) -> None:
        """D6e R4b: default severity is WARNING, not ERROR.

        Proto3-only shops who relied on ERROR can re-promote via
        ``[tool.protokit.lint.severities] "file/syntax-specified"
        = "error"`` (covered by the sibling re-promotion test).
        """
        result = _compile(
            tmp_path,
            {"p2.proto": _SYNTAX_EXPLICIT_PROTO2},
        )
        engine = LintEngine()
        engine.load_rule_pack(file_pack)
        profile = LintProfile.from_pack(file_pack, "recommended")
        report = engine.run(result, profile=profile)
        assert len(report.findings) == 1
        assert report.findings[0].severity is LintSeverity.WARNING

    def test_severities_override_repromotes_to_error(
        self, tmp_path: Path,
    ) -> None:
        """D6e R4b migration recipe: re-promote to ERROR via override.

        Verifies the documented migration path works end-to-end —
        proto3-only shops who relied on the prior ERROR severity
        can restore it via ``[tool.protokit.lint.severities]``.
        """
        from dataclasses import replace

        result = _compile(
            tmp_path,
            {"p2.proto": _SYNTAX_EXPLICIT_PROTO2},
        )
        engine = LintEngine()
        engine.load_rule_pack(file_pack)
        base_profile = LintProfile.from_pack(file_pack, "recommended")
        promoted_profile = replace(
            base_profile,
            rule_severity_overrides={
                "file/syntax-specified": LintSeverity.ERROR,
            },
        )
        report = engine.run(result, profile=promoted_profile)
        assert len(report.findings) == 1
        assert report.findings[0].severity is LintSeverity.ERROR
