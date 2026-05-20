"""D6d U1 — synthetic ``custom/<suffix>`` rule loader integration tests.

End-to-end coverage of
:mod:`protokit.schema.lint._custom_rules`:

- ``build_synthetic_module`` produces a ``ModuleType`` whose ``RULES``
  tuple feeds cleanly through ``LintEngine.load_rule_pack``.
- Single-kind entries materialize one closure under ``custom/<suffix>``.
- Multi-kind entries materialize one closure per kind, with the first
  kind keeping the canonical ``custom/<suffix>`` rule_id and
  subsequent kinds receiving the kind-mangled
  ``custom/<suffix>__<kind>`` rule_id (KD-19 mangling).
- ``synthetic_rule_ids`` returns the same set the loader registers.
- End-to-end engine.run: presence-only rule fires on absence; closed-
  value-set fires on absence + value mismatch; enum identifier value
  comparison works; the unresolved-extension warning path emits
  exactly one ``custom_annotation_extension_unresolved`` warning per
  (rule_id, file) pair.

The proto sources are written via the shared ``_compile`` helper from
``tests/schema/lint/rules/conftest.py``. The extension proto uses
proto2 ``extend`` syntax (proto3 does not allow ``extend``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from protokit.schema.compile import compile_protos_to_result
from protokit.schema.lint._config import CustomAnnotationRuleSpec
from protokit.schema.lint._custom_rules import (
    _SYNTHETIC_MODULE_NAME,
    build_synthetic_module,
    synthetic_rule_ids,
)
from protokit.schema.lint.engine import LintEngine
from protokit.schema.lint.model import (
    ElementKind,
    LintProfile,
    LintSeverity,
)

# ---------------------------------------------------------------------------
# Fixture infrastructure
# ---------------------------------------------------------------------------

EXTENSION_PROTO = """\
syntax = "proto2";

package example;

import "google/protobuf/descriptor.proto";

extend google.protobuf.MethodOptions {
    optional string audit_level_str = 50001;
    optional int32 audit_level_int = 50002;
    optional bool audit_level_bool = 50003;
    optional AuditLevel audit_level_enum = 50005;
}

extend google.protobuf.FieldOptions {
    optional string field_tag = 50006;
}

enum AuditLevel {
    NONE = 0;
    LOW = 1;
    HIGH = 2;
    CRITICAL = 3;
}
"""

SERVICE_PROTO = """\
syntax = "proto3";

package example;

import "example/ext.proto";

service Svc {
    rpc Annotated(Req) returns (Resp) {
        option (example.audit_level_str) = "HIGH";
        option (example.audit_level_int) = 42;
        option (example.audit_level_bool) = true;
        option (example.audit_level_enum) = CRITICAL;
    }
    rpc Bare(Req) returns (Resp);
}

message Req {
    string a = 1 [(example.field_tag) = "client_id"];
    string b = 2;
}

message Resp {
    string r = 1;
}
"""


def _compile_fixture(tmp_path: Path) -> Any:
    """Write the extension + service protos and compile them."""
    ext_path = tmp_path / "example" / "ext.proto"
    svc_path = tmp_path / "example" / "service.proto"
    ext_path.parent.mkdir(parents=True, exist_ok=True)
    ext_path.write_text(EXTENSION_PROTO)
    svc_path.write_text(SERVICE_PROTO)
    return compile_protos_to_result(
        paths=[ext_path, svc_path],
        proto_paths=[str(tmp_path)],
    )


def _run(
    compile_result: Any, specs: list[CustomAnnotationRuleSpec],
) -> Any:
    """Build the synthetic module + run the engine; return the LintReport."""
    engine = LintEngine()
    module = build_synthetic_module(specs, engine)
    assert module is not None
    engine.load_rule_pack(module)
    rule_ids = synthetic_rule_ids(specs)
    profile = LintProfile(
        name="_test",
        rule_ids=rule_ids,
        min_severity=LintSeverity.INFO,
    )
    return engine.run(compile_result, profile=profile)


# ---------------------------------------------------------------------------
# Module structure
# ---------------------------------------------------------------------------


class TestModuleStructure:
    """``build_synthetic_module`` shape contracts."""

    def test_empty_specs_returns_none(self) -> None:
        engine = LintEngine()
        assert build_synthetic_module([], engine) is None

    def test_module_name_is_stable_constant(self) -> None:
        engine = LintEngine()
        spec = CustomAnnotationRuleSpec(
            rule_suffix="x",
            option="y.z",
            element_kinds=(ElementKind.FIELD,),
        )
        module = build_synthetic_module([spec], engine)
        assert module is not None
        assert module.__name__ == _SYNTHETIC_MODULE_NAME

    def test_single_kind_produces_one_closure(self) -> None:
        engine = LintEngine()
        spec = CustomAnnotationRuleSpec(
            rule_suffix="solo",
            option="y.z",
            element_kinds=(ElementKind.FIELD,),
        )
        module = build_synthetic_module([spec], engine)
        assert module is not None
        assert len(module.RULES) == 1
        rule = module.RULES[0]
        assert rule._lint_spec.rule_id == "custom/solo"
        assert rule._lint_spec.element == ElementKind.FIELD

    def test_multi_kind_mangles_subsequent_rule_ids(self) -> None:
        """KD-19: per ElementKind, one closure; first keeps the canonical
        ``custom/<suffix>`` id; subsequent receive ``custom/<suffix>__<kind>``
        so engine staging accepts the multi-kind entry.
        """
        engine = LintEngine()
        spec = CustomAnnotationRuleSpec(
            rule_suffix="audit",
            option="y.z",
            element_kinds=(ElementKind.FIELD, ElementKind.METHOD),
        )
        module = build_synthetic_module([spec], engine)
        assert module is not None
        ids = {rule._lint_spec.rule_id for rule in module.RULES}
        assert ids == {"custom/audit", "custom/audit__method"}

    def test_engine_load_succeeds_for_multi_kind_entry(self) -> None:
        engine = LintEngine()
        spec = CustomAnnotationRuleSpec(
            rule_suffix="audit",
            option="y.z",
            element_kinds=(
                ElementKind.FIELD,
                ElementKind.METHOD,
                ElementKind.MESSAGE,
            ),
        )
        module = build_synthetic_module([spec], engine)
        assert module is not None
        engine.load_rule_pack(module)
        # All 3 closures registered without raising DuplicateRuleError.
        loaded_ids = set(engine._loaded_specs.keys())
        assert {
            "custom/audit",
            "custom/audit__method",
            "custom/audit__message",
        } <= loaded_ids


class TestSyntheticRuleIds:
    """``synthetic_rule_ids`` mirrors the registered rule_ids exactly."""

    def test_single_kind(self) -> None:
        spec = CustomAnnotationRuleSpec(
            rule_suffix="x",
            option="y.z",
            element_kinds=(ElementKind.FIELD,),
        )
        assert synthetic_rule_ids([spec]) == frozenset({"custom/x"})

    def test_multi_kind(self) -> None:
        spec = CustomAnnotationRuleSpec(
            rule_suffix="x",
            option="y.z",
            element_kinds=(ElementKind.FIELD, ElementKind.METHOD),
        )
        assert synthetic_rule_ids([spec]) == frozenset(
            {"custom/x", "custom/x__method"},
        )

    def test_multiple_entries(self) -> None:
        a = CustomAnnotationRuleSpec(
            rule_suffix="a",
            option="x",
            element_kinds=(ElementKind.FIELD,),
        )
        b = CustomAnnotationRuleSpec(
            rule_suffix="b",
            option="x",
            element_kinds=(ElementKind.METHOD,),
        )
        assert synthetic_rule_ids([a, b]) == frozenset(
            {"custom/a", "custom/b"},
        )

    def test_empty(self) -> None:
        assert synthetic_rule_ids([]) == frozenset()


# ---------------------------------------------------------------------------
# End-to-end engine behavior
# ---------------------------------------------------------------------------


class TestPresenceOnly:
    """Closure body fires only when the configured option is absent."""

    def test_method_presence_only_fires_on_bare(self, tmp_path: Path) -> None:
        result = _compile_fixture(tmp_path)
        spec = CustomAnnotationRuleSpec(
            rule_suffix="audit-needed",
            option="example.audit_level_str",
            element_kinds=(ElementKind.METHOD,),
            severity=LintSeverity.WARNING,
        )
        report = _run(result, [spec])
        # The Annotated method has audit_level_str = "HIGH" set;
        # Bare has no annotations. Exactly one finding on Bare.
        assert len(report.findings) == 1
        finding = report.findings[0]
        assert finding.rule_id == "custom/audit-needed"
        assert finding.violation_kind == "custom-annotation-absent"
        assert "Bare" in str(finding.location)

    def test_field_presence_only_fires_on_unannotated(self, tmp_path: Path) -> None:
        result = _compile_fixture(tmp_path)
        spec = CustomAnnotationRuleSpec(
            rule_suffix="tag-needed",
            option="example.field_tag",
            element_kinds=(ElementKind.FIELD,),
        )
        report = _run(result, [spec])
        # ``Req.a`` has field_tag = "client_id" → no finding.
        # ``Req.b`` + ``Resp.r`` lack the annotation → 2 findings.
        assert len(report.findings) == 2
        assert all(
            f.violation_kind == "custom-annotation-absent"
            for f in report.findings
        )
        locations = {str(f.location) for f in report.findings}
        assert any(".b" in loc for loc in locations)
        assert any(".r" in loc for loc in locations)


class TestClosedValueSet:
    """Closure fires on absence AND on value mismatch."""

    def test_string_allowed_values_passes_when_value_in_set(
        self, tmp_path: Path,
    ) -> None:
        result = _compile_fixture(tmp_path)
        spec = CustomAnnotationRuleSpec(
            rule_suffix="audit-required",
            option="example.audit_level_str",
            element_kinds=(ElementKind.METHOD,),
            allowed_values=("HIGH", "CRITICAL"),
        )
        report = _run(result, [spec])
        # Annotated method has audit_level_str = "HIGH" → in set → no
        # finding. Bare method has no annotation → presence violation.
        kinds = sorted(f.violation_kind for f in report.findings)
        assert kinds == ["custom-annotation-absent"]

    def test_string_value_mismatch_fires(self, tmp_path: Path) -> None:
        result = _compile_fixture(tmp_path)
        # Allow only "CRITICAL" — the Annotated method's "HIGH" should mismatch.
        spec = CustomAnnotationRuleSpec(
            rule_suffix="audit-critical-only",
            option="example.audit_level_str",
            element_kinds=(ElementKind.METHOD,),
            allowed_values=("CRITICAL",),
        )
        report = _run(result, [spec])
        kinds = sorted(f.violation_kind for f in report.findings)
        # Two findings: Annotated mismatches ("HIGH" not in {"CRITICAL"}),
        # Bare is absent.
        assert kinds == ["custom-annotation-absent", "custom-annotation-value-mismatch"]
        mismatch = next(
            f
            for f in report.findings
            if f.violation_kind == "custom-annotation-value-mismatch"
        )
        assert mismatch.params["actual_value"] == "HIGH"

    def test_enum_identifier_value_comparison(self, tmp_path: Path) -> None:
        """Enum extensions return integer values at runtime; the closure
        must translate to the identifier string before comparing
        against ``allowed_values`` written as identifiers.
        """
        result = _compile_fixture(tmp_path)
        spec = CustomAnnotationRuleSpec(
            rule_suffix="audit-level",
            option="example.audit_level_enum",
            element_kinds=(ElementKind.METHOD,),
            allowed_values=("HIGH", "CRITICAL"),
        )
        report = _run(result, [spec])
        # Annotated has audit_level_enum = CRITICAL → identifier match
        # → no finding. Bare has no annotation → presence violation.
        kinds = sorted(f.violation_kind for f in report.findings)
        assert kinds == ["custom-annotation-absent"]

    def test_signed_int_comparison(self, tmp_path: Path) -> None:
        """Int values pass through unchanged; positive_int and
        negative_int both compare correctly under equality."""
        result = _compile_fixture(tmp_path)
        spec = CustomAnnotationRuleSpec(
            rule_suffix="audit-int",
            option="example.audit_level_int",
            element_kinds=(ElementKind.METHOD,),
            allowed_values=(42, -7),
        )
        report = _run(result, [spec])
        # Annotated has audit_level_int = 42 → match → no finding.
        # Bare has no annotation → presence violation.
        kinds = sorted(f.violation_kind for f in report.findings)
        assert kinds == ["custom-annotation-absent"]

    def test_bool_comparison(self, tmp_path: Path) -> None:
        result = _compile_fixture(tmp_path)
        spec = CustomAnnotationRuleSpec(
            rule_suffix="audit-bool",
            option="example.audit_level_bool",
            element_kinds=(ElementKind.METHOD,),
            allowed_values=(True,),
        )
        report = _run(result, [spec])
        # Annotated has audit_level_bool = true → match → no finding.
        # Bare absent → presence violation.
        kinds = sorted(f.violation_kind for f in report.findings)
        assert kinds == ["custom-annotation-absent"]


class TestUnresolvedExtension:
    """KeyError on FindExtensionByName → 1 runtime warning per (rule_id, file)."""

    def test_unknown_extension_skips_with_warning(
        self, tmp_path: Path,
    ) -> None:
        result = _compile_fixture(tmp_path)
        spec = CustomAnnotationRuleSpec(
            rule_suffix="phantom",
            option="notinpool.bogus",
            element_kinds=(ElementKind.METHOD,),
        )
        report = _run(result, [spec])
        # Zero findings (we cannot evaluate without the extension).
        assert report.findings == ()
        # Exactly one warning per file — both methods live in
        # service.proto, so the dedup keeps it at 1.
        unresolved = [
            w
            for w in report.runtime_warnings
            if w.category == "custom_annotation_extension_unresolved"
        ]
        assert len(unresolved) == 1
        assert unresolved[0].rule_id == "custom/phantom"
        assert "notinpool.bogus" in unresolved[0].message

    def test_unresolved_dedups_across_element_kinds(
        self, tmp_path: Path,
    ) -> None:
        """Multi-kind entry: closures for FIELD + METHOD share the same
        dedup set so a single (rule_id, file) emits one warning total.
        """
        result = _compile_fixture(tmp_path)
        spec = CustomAnnotationRuleSpec(
            rule_suffix="phantom-multi",
            option="notinpool.bogus",
            element_kinds=(ElementKind.METHOD, ElementKind.FIELD),
        )
        # Build manually so we can target both rule_ids in the profile.
        engine = LintEngine()
        module = build_synthetic_module([spec], engine)
        assert module is not None
        engine.load_rule_pack(module)
        profile = LintProfile(
            name="_test",
            rule_ids=synthetic_rule_ids([spec]),
            min_severity=LintSeverity.INFO,
        )
        report = engine.run(result, profile=profile)
        unresolved = [
            w
            for w in report.runtime_warnings
            if w.category == "custom_annotation_extension_unresolved"
        ]
        # The two closures (FIELD + METHOD) share the same per-spec
        # ``unresolved_seen`` set and emit the warning under the spec's
        # BASE ``rule_id`` (``custom/phantom-multi``, NOT the kind-
        # mangled variant). The dedup is keyed on (rule_id, file_name)
        # so a single ``(custom/phantom-multi, example/service.proto)``
        # entry collapses to ONE warning across both closures'
        # invocations.
        assert len(unresolved) == 1
        assert unresolved[0].rule_id == "custom/phantom-multi"


class TestSeverityOverride:
    """``[severities]`` table demotes synthetic-rule findings."""

    def test_severities_overlay_demotes_synthetic_to_info(
        self, tmp_path: Path,
    ) -> None:
        """When ``severities = {"custom/x" = "info"}`` is configured,
        the synthetic rule's findings emit at ``info`` regardless of
        the spec's declared severity.
        """
        result = _compile_fixture(tmp_path)
        spec = CustomAnnotationRuleSpec(
            rule_suffix="x",
            option="example.audit_level_str",
            element_kinds=(ElementKind.METHOD,),
            severity=LintSeverity.ERROR,
        )
        engine = LintEngine()
        module = build_synthetic_module([spec], engine)
        assert module is not None
        engine.load_rule_pack(module)
        profile = LintProfile(
            name="_test",
            rule_ids=synthetic_rule_ids([spec]),
            min_severity=LintSeverity.INFO,
            rule_severity_overrides={"custom/x": LintSeverity.INFO},
        )
        report = engine.run(result, profile=profile)
        assert all(
            f.severity == LintSeverity.INFO for f in report.findings
        )


class TestProfileIndependence:
    """KD-12: synthetic rules fire whenever they're in ``profile.rule_ids``."""

    def test_synthetic_rule_fires_under_any_profile_name(
        self, tmp_path: Path,
    ) -> None:
        """The profile name doesn't gate synthetic-rule firing; only
        membership in ``profile.rule_ids`` does. This mirrors built-in
        rule semantics — name vs rule_ids membership are decoupled.
        """
        result = _compile_fixture(tmp_path)
        spec = CustomAnnotationRuleSpec(
            rule_suffix="x",
            option="example.audit_level_str",
            element_kinds=(ElementKind.METHOD,),
        )
        engine = LintEngine()
        module = build_synthetic_module([spec], engine)
        assert module is not None
        engine.load_rule_pack(module)
        for profile_name in ("recommended", "default", "essentials", "made-up-name"):
            profile = LintProfile(
                name=profile_name,
                rule_ids=synthetic_rule_ids([spec]),
                min_severity=LintSeverity.INFO,
            )
            report = engine.run(result, profile=profile)
            assert len(report.findings) >= 1, (
                f"synthetic rule did not fire under profile {profile_name!r}"
            )
