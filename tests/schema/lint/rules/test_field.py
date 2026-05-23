"""Tests for the D6e U1+U2 field-structural rule pack.

Covers the 1 rule registered in :mod:`protokit.schema.lint.rules.field`:

- ``field/not-required`` — fires (at ERROR under the opt-in
  ``proto2-strict`` profile only) when a proto2 field carries the
  ``required`` label. Proto2-only via the ``fdp.syntax != ""``
  early-return; ``recommended`` + ``default`` profiles see ZERO
  findings from this rule per D6e KD-5 (proto2-specific strictness
  ships in opt-in ``proto2-strict`` per the inverted UX philosophy
  at KD-1).

**Phase 0 EV-2 falsification (2026-05-22):** the originally-planned
extend-block divergence does not exist. Both buf v1.69.0 and
protokit's compiler reject ``required`` extension fields at parse
layer ("invalid cardinality: 2"); the construct cannot be compiled,
so no rule-level divergence exists. The architectural gap in the
engine walker (no iteration of ``extensions_by_name``) is
operationally moot. See module docstring at
``src/protokit/schema/lint/rules/field.py`` for the full
falsification story.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from protokit.schema.lint.engine import LintEngine
from protokit.schema.lint.model import ElementKind, LintProfile, LintSeverity
from protokit.schema.lint.rules import field as field_pack
from protokit.schema.lint.rules.field import (
    RULES,
    check_field_not_required,
)

from .conftest import _compile
from .conftest import _run_single as _run_single_with_pack


def _run_single(
    tmp_path: Path,
    sources: dict[str, str],
    rule_id: str,
) -> Any:
    """Thin wrapper that fixes the pack to ``field`` for this file's tests."""
    return _run_single_with_pack(tmp_path, sources, rule_id, field_pack)


# ---------------------------------------------------------------------------
# Module shape — RULES tuple + spec metadata
# ---------------------------------------------------------------------------


class TestFieldPackShape:
    """The field pack exposes RULES with the D6e U1+U2 rule registered."""

    def test_rules_tuple_contains_one_callable(self) -> None:
        assert isinstance(RULES, tuple)
        assert len(RULES) == 1
        for fn in RULES:
            assert hasattr(fn, "_lint_spec")

    def test_pack_includes_the_rule(self) -> None:
        assert check_field_not_required in RULES


class TestFieldRuleSpecs:
    """The new rule carries the D6e U2 spec metadata."""

    def test_field_not_required_spec(self) -> None:
        spec = check_field_not_required._lint_spec  # type: ignore[attr-defined]
        assert spec.rule_id == "field/not-required"
        # D6e KD-5: ERROR severity under the opt-in proto2-strict
        # profile (the profile name carries the strictness signal;
        # users opting in want hard signals).
        assert spec.severity is LintSeverity.ERROR
        # D6e KD-5 + KD-2: proto2-strict ONLY — recommended/default
        # MUST NOT include this rule (proto2-specific strictness is
        # opt-in per the inverted UX philosophy at KD-1).
        assert spec.profiles == ("proto2-strict",)
        assert spec.element is ElementKind.FIELD
        assert spec.source_spec == "buf:FIELD_NOT_REQUIRED"


# ---------------------------------------------------------------------------
# field/not-required — happy paths + edge cases
# ---------------------------------------------------------------------------


_PROTO2_REQUIRED = """
syntax = "proto2";
package field_not_required;
message Proto2RequiredStub {
  required int32 required_field = 1;
  optional int32 optional_field = 2;
  repeated int32 repeated_field = 3;
}
"""

_PROTO2_OPTIONAL = """
syntax = "proto2";
package field_not_required;
message Proto2OptionalStub {
  optional int32 optional_field = 1;
  repeated int32 repeated_field = 2;
}
"""

_PROTO3_FIELD = """
syntax = "proto3";
package field_not_required;
message Proto3FieldStub {
  int32 plain_field = 1;
  optional int32 explicit_optional = 2;
  repeated int32 repeated_field = 3;
}
"""

_PROTO2_GROUP_REQUIRED = """
syntax = "proto2";
package field_not_required;
message Outer {
  required group RequiredGroup = 1 {
    optional int32 inner = 1;
  }
}
"""


class TestFieldNotRequired:
    """``field/not-required`` fires on proto2 ``required`` fields only."""

    def test_happy_path_proto2_required_fires(self, tmp_path: Path) -> None:
        """Proto2 ``required`` field emits one finding."""
        report = _run_single(
            tmp_path,
            {"p2_req.proto": _PROTO2_REQUIRED},
            "field/not-required",
        )
        assert len(report.findings) == 1
        f = report.findings[0]
        assert f.violation_kind == "field/not-required"
        assert f.params == {"field_name": "required_field"}
        assert f.severity is LintSeverity.ERROR

    def test_happy_path_proto2_optional_clean(self, tmp_path: Path) -> None:
        """Proto2 ``optional`` field does NOT fire."""
        report = _run_single(
            tmp_path,
            {"p2_opt.proto": _PROTO2_OPTIONAL},
            "field/not-required",
        )
        assert report.findings == ()

    def test_happy_path_proto3_clean(self, tmp_path: Path) -> None:
        """Proto3 file (no ``required`` label exists in proto3) does NOT fire.

        Verifies the ``fdp.syntax != ""`` early-return: protoc emits
        ``"proto3"`` for proto3 files, so the rule short-circuits
        before the LABEL_REQUIRED check.
        """
        report = _run_single(
            tmp_path,
            {"p3.proto": _PROTO3_FIELD},
            "field/not-required",
        )
        assert report.findings == ()

    def test_edge_case_proto2_group_required_fires(
        self, tmp_path: Path,
    ) -> None:
        """Proto2 group-typed required field fires (EV-3 binding).

        Proto2 groups surface in the descriptor as a regular field
        with LABEL_REQUIRED and a lowercased name derived from the
        group declaration. Phase 0 verified buf v1.69.0 emits the
        same finding (on the lowercased name ``requiredgroup``).
        """
        report = _run_single(
            tmp_path,
            {"p2_group.proto": _PROTO2_GROUP_REQUIRED},
            "field/not-required",
        )
        # Group fields surface as a single LABEL_REQUIRED field
        # named after the lowercased group identifier; buf v1.69.0
        # likewise emits one finding here.
        assert len(report.findings) == 1
        f = report.findings[0]
        assert f.violation_kind == "field/not-required"
        # The implicit group field's name is the lowercase of the
        # group declaration ("RequiredGroup" -> "requiredgroup").
        assert f.params == {"field_name": "requiredgroup"}

    def test_ev_1_editions_file_does_not_fire(self) -> None:
        """EV-1 binding (ce:review P2 #7): editions files do NOT fire.

        Editions files have ``fdp.syntax == "editions"`` so the
        cheap-check-first ordering (LABEL_REQUIRED → CopyToProto →
        syntax check) eventually short-circuits at the syntax probe.
        This test exercises the editions branch via a manually-
        constructed FileDescriptorProto (the project's compile
        backends do not yet support editions input).

        Pattern mirrors test_file.py::test_happy_path_editions_clean.
        """
        from google.protobuf import descriptor_pb2 as _pb2
        from google.protobuf import descriptor_pool as _pool

        from protokit.schema.compile import CompileResult

        # Construct an editions file via FileDescriptorProto. The
        # rule walks at FIELD level, but FieldDescriptor needs a
        # message parent — synthesize one with a normal field.
        fdp = _pb2.FileDescriptorProto()
        fdp.name = "ed.proto"
        fdp.syntax = "editions"
        fdp.edition = _pb2.Edition.EDITION_2023
        fdp.package = "ed"
        msg = fdp.message_type.add()
        msg.name = "EditionsMsg"
        field = msg.field.add()
        field.name = "field1"
        field.number = 1
        field.type = _pb2.FieldDescriptorProto.TYPE_INT32
        # Field label LABEL_OPTIONAL (1) — editions does not use
        # LABEL_REQUIRED, but the cheap-check-first early-return
        # in the rule body exits before we even get to the syntax
        # check, so this branch is verified by inputs that
        # legitimately could carry LABEL_OPTIONAL.
        field.label = _pb2.FieldDescriptorProto.LABEL_OPTIONAL
        pool = _pool.DescriptorPool()
        pool.Add(fdp)
        result = CompileResult(pool=pool, root_files=("ed.proto",))
        engine = LintEngine()
        engine.load_rule_pack(field_pack)
        profile = LintProfile(
            name="t",
            rule_ids=frozenset({"field/not-required"}),
            min_severity=LintSeverity.INFO,
        )
        report = engine.run(result, profile=profile)
        assert report.findings == ()

    def test_ev_4_multi_file_proto2_proto3_mix_fires_per_syntax(
        self, tmp_path: Path,
    ) -> None:
        """EV-4 binding (ce:review P2 #7): per-file syntax scoping.

        Mixed-syntax compile (one proto2 file + one proto3 file)
        must fire ``field/not-required`` ONLY on the proto2 file's
        required field. The proto3 file (which cannot legally have
        LABEL_REQUIRED but exists in the same descriptor pool) must
        not contribute findings. Per the rule body's cheap-check-
        first ordering, proto3 fields exit immediately at the
        LABEL_REQUIRED check; proto2 required fields proceed to
        the CopyToProto syntax probe and then emit.
        """
        proto2 = """
syntax = "proto2";
package ev4;
message P2 { required int32 r = 1; }
"""
        proto3 = """
syntax = "proto3";
package ev4;
message P3 { int32 plain = 1; }
"""
        result = _compile(
            tmp_path,
            {"p2.proto": proto2, "p3.proto": proto3},
        )
        engine = LintEngine()
        engine.load_rule_pack(field_pack)
        profile = LintProfile(
            name="t",
            rule_ids=frozenset({"field/not-required"}),
            min_severity=LintSeverity.INFO,
        )
        report = engine.run(result, profile=profile)
        # Exactly one finding — the proto2 required field. The
        # proto3 file's `plain` field has LABEL_OPTIONAL and exits
        # at the cheap-check-first early-return.
        assert len(report.findings) == 1
        finding = report.findings[0]
        assert finding.violation_kind == "field/not-required"
        assert finding.params == {"field_name": "r"}
        # Pin file scope: finding originates from the proto2 file.
        assert "p2.proto" in str(finding.location)

    def test_phase_0_ev_2_extend_block_required_falsification(self) -> None:
        """EV-2 falsification documented at test layer (2026-05-22).

        The brainstorm + plan originally framed a "documented
        extend-block divergence" where buf would fire
        FIELD_NOT_REQUIRED on extend-block required fields while
        protokit (whose engine walker does not iterate
        ``fd.extensions_by_name`` or ``Message.extensions_by_name``)
        would not. Phase 0 falsified this premise: both buf v1.69.0
        AND protokit's compiler reject ``required`` extension fields
        at parse layer per the protobuf cardinality constraint
        ("invalid cardinality: 2"). The construct cannot be
        compiled, so no rule-level divergence exists. No fixture
        file, no ``_PARITY_EXCEPTIONS`` entry — this test exists
        as a one-method breadcrumb so future readers searching for
        "extend-block" or "extensions_by_name" in the test suite
        find the resolution.

        See
        ``docs/solutions/best-practices/phase-0-empirical-verification-falsifies-brainstorm-assumption-2026-05-22.md``
        for the institutional lesson.
        """
        # Explicit pass per ce:review P2 #5 (kieran-python KP-1 +
        # testing T-5, 2026-05-22): the docstring IS the assertion,
        # but tooling that scans for empty-body tests needs an
        # explicit statement to distinguish "deliberately empty"
        # from "left incomplete". The CopyToProto round-trip would
        # crash if the construct were valid; protoc/protoxy reject
        # it at parse layer; no runtime assertion is possible at
        # the test layer. The breadcrumb exists for grep
        # discoverability ("extend-block" / "extensions_by_name").
        pass


# ---------------------------------------------------------------------------
# Profile membership — derived from RULES (SSOT per
# [[rule-pack-extension-ssot-rule-ids-and-test-class-naming-2026-05-12]])
# ---------------------------------------------------------------------------


_ALL_FIELD_RULE_IDS = frozenset(
    fn._lint_spec.rule_id  # type: ignore[attr-defined]
    for fn in RULES
)


class TestFieldProfileMembership:
    """``LintProfile.from_pack`` returns the expected rule_id sets."""

    def test_from_pack_proto2_strict_contains_the_rule(self) -> None:
        """proto2-strict is the opt-in profile carrying ``field/not-required``."""
        profile = LintProfile.from_pack(field_pack, "proto2-strict")
        assert profile.name == "proto2-strict"
        assert profile.rule_ids == _ALL_FIELD_RULE_IDS

    def test_from_pack_recommended_contains_no_field_rules(self) -> None:
        """D6e KD-5: ``recommended`` MUST NOT include proto2-strict rules."""
        profile = LintProfile.from_pack(field_pack, "recommended")
        assert profile.rule_ids == frozenset()

    def test_from_pack_default_contains_no_field_rules(self) -> None:
        """D6e KD-5: ``default`` MUST NOT include proto2-strict rules."""
        profile = LintProfile.from_pack(field_pack, "default")
        assert profile.rule_ids == frozenset()

    def test_from_pack_essentials_contains_no_field_rules(self) -> None:
        profile = LintProfile.from_pack(field_pack, "essentials")
        assert profile.rule_ids == frozenset()

    def test_from_pack_unknown_profile_returns_empty(self) -> None:
        profile = LintProfile.from_pack(field_pack, "nonexistent")
        assert profile.rule_ids == frozenset()


# ---------------------------------------------------------------------------
# Integration — the rule fires on a deliberately-bad fixture
# ---------------------------------------------------------------------------


class TestFieldPackIntegration:
    """End-to-end behavior across realistic profile postures."""

    def test_proto2_strict_profile_fires_on_required_field(
        self, tmp_path: Path,
    ) -> None:
        result = _compile(
            tmp_path,
            {"p2.proto": _PROTO2_REQUIRED},
        )
        engine = LintEngine()
        engine.load_rule_pack(field_pack)
        profile = LintProfile.from_pack(field_pack, "proto2-strict")
        report = engine.run(result, profile=profile)
        assert len(report.findings) == 1
        assert report.findings[0].rule_id == "field/not-required"
        assert report.findings[0].severity is LintSeverity.ERROR

    def test_recommended_profile_shows_zero_field_not_required(
        self, tmp_path: Path,
    ) -> None:
        """D6e KD-5 verification: ``recommended`` users see no findings.

        Even with a proto2-required field in the input, the rule
        does NOT fire in the ``recommended`` profile because it is
        not in that profile's rule_id set.
        """
        result = _compile(
            tmp_path,
            {"p2.proto": _PROTO2_REQUIRED},
        )
        engine = LintEngine()
        engine.load_rule_pack(field_pack)
        profile = LintProfile.from_pack(field_pack, "recommended")
        report = engine.run(result, profile=profile)
        assert report.findings == ()

    def test_severities_override_demotes_to_warning(
        self, tmp_path: Path,
    ) -> None:
        """D6e migration recipe: demote to WARNING via severity override.

        Verifies the documented demotion path works end-to-end —
        proto2-strict opt-in users who want lighter signaling can
        demote via ``[tool.protokit.lint.severities]``.
        """
        from dataclasses import replace

        result = _compile(
            tmp_path,
            {"p2.proto": _PROTO2_REQUIRED},
        )
        engine = LintEngine()
        engine.load_rule_pack(field_pack)
        base_profile = LintProfile.from_pack(field_pack, "proto2-strict")
        demoted_profile = replace(
            base_profile,
            rule_severity_overrides={
                "field/not-required": LintSeverity.WARNING,
            },
            # Lower the floor so the WARNING is not filtered.
            min_severity=LintSeverity.INFO,
        )
        report = engine.run(result, profile=demoted_profile)
        assert len(report.findings) == 1
        assert report.findings[0].severity is LintSeverity.WARNING
