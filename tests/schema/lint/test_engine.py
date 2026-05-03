"""Tests for :mod:`protokit.schema.lint.engine`.

Cover load_rule_pack atomicity / idempotency / reset, walk semantics
(R4-R6: only root_files; per-level full_name sort; tie-break),
unloaded-rule warning, severity resolution + filtered_count, narrow
catch tuple including SystemExit (R16 amendment), and
CompileResult.diagnostics passthrough.
"""

from __future__ import annotations

import types
from pathlib import Path
from typing import Any

import pytest

from protokit.schema.compile import LintCompileDiagnostic, compile_protos_to_result
from protokit.schema.lint.decorator import lint_rule
from protokit.schema.lint.engine import LintEngine
from protokit.schema.lint.model import (
    DuplicateRuleError,
    ElementKind,
    LintProfile,
    LintRuleError,
    LintSeverity,
)

# ---------------------------------------------------------------------------
# Test helpers — synthetic packs and compile fixtures.
# ---------------------------------------------------------------------------


def _make_pack(name: str, fns: tuple[Any, ...]) -> types.ModuleType:
    """Construct a throwaway module with __name__=name and RULES=fns."""
    mod = types.ModuleType(name)
    mod.RULES = fns
    return mod


def _compile(tmp_path: Path, sources: dict[str, str]) -> Any:
    """Write inline proto sources to tmp_path; return CompileResult.

    ``sources`` maps relative .proto file name to its contents. All
    files are written under ``tmp_path``; ``compile_protos_to_result``
    is invoked over every file as a root.
    """
    paths: list[Path] = []
    for fname, text in sources.items():
        p = tmp_path / fname
        p.write_text(text)
        paths.append(p)
    return compile_protos_to_result(paths=paths, proto_paths=(str(tmp_path),))


def _decorated_field_rule(rule_id: str, *, profiles: tuple[str, ...] = ("default",),
                          severity: LintSeverity = LintSeverity.WARNING) -> Any:
    """Build a synthetic FIELD rule that emits one finding per field."""

    @lint_rule(
        rule_id=rule_id,
        severity=severity,
        profiles=profiles,
        element=ElementKind.FIELD,
        message_template="emitted by " + rule_id,
    )
    def rule(ctx: Any) -> None:
        ctx.emit(violation_kind=rule_id)

    rule.__name__ = f"rule_{rule_id.replace('/', '_').replace('-', '_')}"
    return rule


# ---------------------------------------------------------------------------
# load_rule_pack: atomicity, idempotency, errors
# ---------------------------------------------------------------------------


class TestLoadRulePack:
    """Per-instance registry behavior with stage-then-commit semantics."""

    def test_loads_rules_from_module_RULES(self) -> None:  # noqa: N802 — plan-spec name echoes module attr
        rule_a = _decorated_field_rule("a/one")
        rule_b = _decorated_field_rule("a/two")
        pack = _make_pack("pack_a", (rule_a, rule_b))
        engine = LintEngine()
        engine.load_rule_pack(pack)
        assert set(engine._loaded_specs.keys()) == {"a/one", "a/two"}
        assert "pack_a" in engine._loaded_module_names

    def test_idempotent_for_same_module(self) -> None:
        rule_a = _decorated_field_rule("a/one")
        pack = _make_pack("pack_idem", (rule_a,))
        engine = LintEngine()
        engine.load_rule_pack(pack)
        engine.load_rule_pack(pack)  # second call short-circuits
        assert len(engine._loaded_specs) == 1
        assert engine._loaded_module_names == {"pack_idem"}

    def test_intra_pack_duplicate_raises_atomically(self) -> None:
        rule_a = _decorated_field_rule("dup/x")
        rule_a_clone = _decorated_field_rule("dup/x")
        pack = _make_pack("pack_dup_intra", (rule_a, rule_a_clone))
        engine = LintEngine()
        with pytest.raises(DuplicateRuleError, match="dup/x"):
            engine.load_rule_pack(pack)
        # Engine state unchanged.
        assert engine._loaded_specs == {}
        assert engine._loaded_module_names == set()

    def test_cross_pack_duplicate_raises_atomically(self) -> None:
        rule_a = _decorated_field_rule("a/dup")
        rule_b1 = _decorated_field_rule("b/one")
        rule_b2 = _decorated_field_rule("a/dup")  # collides with pack A
        engine = LintEngine()
        engine.load_rule_pack(_make_pack("pack_cross_a", (rule_a,)))
        before_specs = dict(engine._loaded_specs)
        before_modules = set(engine._loaded_module_names)
        with pytest.raises(DuplicateRuleError, match="a/dup"):
            engine.load_rule_pack(_make_pack("pack_cross_b", (rule_b1, rule_b2)))
        # Atomic rollback — pack B did not partially load b/one.
        assert engine._loaded_specs == before_specs
        assert engine._loaded_module_names == before_modules

    def test_missing_RULES_attribute_raises(self) -> None:  # noqa: N802 — echoes module attr
        mod = types.ModuleType("pack_no_rules")
        engine = LintEngine()
        with pytest.raises(AttributeError, match="RULES"):
            engine.load_rule_pack(mod)

    def test_undecorated_fn_in_RULES_raises_typeerror(self) -> None:  # noqa: N802 — echoes module attr
        def undecorated(_ctx: Any) -> None:
            return None

        pack = _make_pack("pack_undecorated", (undecorated,))
        engine = LintEngine()
        with pytest.raises(TypeError, match="not @lint_rule-decorated"):
            engine.load_rule_pack(pack)
        assert engine._loaded_specs == {}

    def test_reset_clears_state(self) -> None:
        rule_a = _decorated_field_rule("a/one")
        engine = LintEngine()
        engine.load_rule_pack(_make_pack("pack_reset", (rule_a,)))
        engine.reset()
        assert engine._loaded_specs == {}
        assert engine._loaded_module_names == set()
        # Reloading the same pack after reset succeeds.
        engine.load_rule_pack(_make_pack("pack_reset", (rule_a,)))
        assert "a/one" in engine._loaded_specs


# ---------------------------------------------------------------------------
# Run: walk semantics + sort order
# ---------------------------------------------------------------------------


_TWO_MSG_PROTO = """
syntax = "proto3";
package example;

message Z {
  string z_field = 1;
}

message M {
  string m_field = 1;
}

message A {
  string a_field = 1;
}
"""


class TestWalkOrder:
    """Verify per-level full_name sort + walk order."""

    def test_walk_only_root_files_skips_imports(self, tmp_path: Path) -> None:
        sources = {
            "vendored.proto": (
                'syntax = "proto3";\n'
                "package vendored;\n"
                "message C {\n"
                "  string c_bad_Field = 1;\n"  # Would fire if walked
                "}\n"
            ),
            "root.proto": (
                'syntax = "proto3";\n'
                "package root;\n"
                'import "vendored.proto";\n'
                "message A {\n"
                "  vendored.C ref = 1;\n"
                "  string a_field = 2;\n"
                "}\n"
            ),
        }
        # Compile only root.proto as a root; vendored.proto is import-only.
        p_root = tmp_path / "root.proto"
        p_vend = tmp_path / "vendored.proto"
        p_root.write_text(sources["root.proto"])
        p_vend.write_text(sources["vendored.proto"])
        result = compile_protos_to_result(
            paths=[p_root], proto_paths=(str(tmp_path),),
        )

        rule = _decorated_field_rule("walk/all-fields")
        engine = LintEngine()
        engine.load_rule_pack(_make_pack("walk_pack_only_root", (rule,)))
        report = engine.run(
            result,
            profile=LintProfile(
                name="x", rule_ids=frozenset({"walk/all-fields"}),
                min_severity=LintSeverity.INFO,
            ),
        )
        # Findings must target only root.proto's fields, never vendored.proto.
        files_seen = {f.location.file for f in report.findings}  # type: ignore[attr-defined]
        assert files_seen == {"root.proto"}

    def test_per_level_sort_by_full_name(self, tmp_path: Path) -> None:
        result = _compile(tmp_path, {"types.proto": _TWO_MSG_PROTO})
        rule = _decorated_field_rule("walk/all-fields")
        engine = LintEngine()
        engine.load_rule_pack(_make_pack("walk_sort_pack", (rule,)))
        report = engine.run(
            result,
            profile=LintProfile(
                name="x", rule_ids=frozenset({"walk/all-fields"}),
                min_severity=LintSeverity.INFO,
            ),
        )
        # Three messages A, M, Z each with one field; sort by full_name yields
        # example.A.a_field, example.M.m_field, example.Z.z_field.
        msgs_in_order = [
            f.location.message  # type: ignore[attr-defined]
            for f in report.findings
        ]
        assert msgs_in_order == ["example.A", "example.M", "example.Z"]


# ---------------------------------------------------------------------------
# Run: empty root_files + unloaded-rule warning
# ---------------------------------------------------------------------------


class TestRunEdgeCases:
    """Empty root_files behavior; unloaded-rule warnings."""

    def test_empty_root_files_no_findings_no_warnings(self, tmp_path: Path) -> None:
        # Synthesize an empty CompileResult (no roots).
        from google.protobuf import descriptor_pool

        from protokit.schema.compile import CompileResult

        empty_result = CompileResult(
            pool=descriptor_pool.DescriptorPool(),
            root_files=(),
            diagnostics=(),
        )
        rule = _decorated_field_rule("empty/test")
        engine = LintEngine()
        engine.load_rule_pack(_make_pack("empty_pack", (rule,)))
        report = engine.run(
            empty_result,
            profile=LintProfile(
                name="x", rule_ids=frozenset({"empty/test"}),
                min_severity=LintSeverity.INFO,
            ),
        )
        assert report.findings == ()
        assert report.runtime_warnings == ()

    def test_unloaded_rule_warns_once_before_walk(self, tmp_path: Path) -> None:
        result = _compile(tmp_path, {"types.proto": _TWO_MSG_PROTO})
        loaded = _decorated_field_rule("loaded/rule")
        engine = LintEngine()
        engine.load_rule_pack(_make_pack("partial_pack", (loaded,)))
        report = engine.run(
            result,
            profile=LintProfile(
                name="x",
                rule_ids=frozenset({"loaded/rule", "missing/one", "missing/two"}),
                min_severity=LintSeverity.INFO,
            ),
        )
        # Two unloaded-rule warnings, regardless of walk size.
        unloaded = [
            w for w in report.runtime_warnings if w.category == "unloaded_rule"
        ]
        assert len(unloaded) == 2
        assert {w.rule_id for w in unloaded} == {"missing/one", "missing/two"}
        # Loaded rule's findings still present.
        assert any(
            f.rule_id == "loaded/rule" for f in report.findings
        )


# ---------------------------------------------------------------------------
# Run: severity resolution + min-severity filter + filtered_count
# ---------------------------------------------------------------------------


class TestSeverityAndFilter:
    """Severity-override application; filter-at-emit + filtered_count."""

    def test_min_severity_filter_increments_filtered_count(
        self, tmp_path: Path,
    ) -> None:
        result = _compile(tmp_path, {"types.proto": _TWO_MSG_PROTO})
        rule = _decorated_field_rule("info/rule", severity=LintSeverity.INFO)
        engine = LintEngine()
        engine.load_rule_pack(_make_pack("filter_pack", (rule,)))
        report = engine.run(
            result,
            profile=LintProfile(
                name="x", rule_ids=frozenset({"info/rule"}),
                min_severity=LintSeverity.WARNING,  # filter out INFO
            ),
        )
        assert report.findings == ()
        # Three messages × one field each = 3 emits, all filtered.
        assert report.filtered_count == 3

    def test_severity_override_promotes_finding_severity(
        self, tmp_path: Path,
    ) -> None:
        result = _compile(tmp_path, {"types.proto": _TWO_MSG_PROTO})
        rule = _decorated_field_rule("info/rule", severity=LintSeverity.INFO)
        engine = LintEngine()
        engine.load_rule_pack(_make_pack("severity_pack", (rule,)))
        report = engine.run(
            result,
            profile=LintProfile(
                name="x", rule_ids=frozenset({"info/rule"}),
                min_severity=LintSeverity.WARNING,
                rule_severity_overrides={"info/rule": LintSeverity.ERROR},
            ),
        )
        # Override promotes to ERROR which passes the WARNING gate.
        assert len(report.findings) == 3
        assert all(f.severity is LintSeverity.ERROR for f in report.findings)
        assert report.filtered_count == 0


# ---------------------------------------------------------------------------
# Run: rule-failure containment
# ---------------------------------------------------------------------------


class TestFailureContainment:
    """Narrow catch tuple including SystemExit (R16 amendment)."""

    def test_value_error_caught_records_runtime_warning(
        self, tmp_path: Path,
    ) -> None:
        result = _compile(tmp_path, {"types.proto": _TWO_MSG_PROTO})

        @lint_rule(
            rule_id="bad/value",
            severity=LintSeverity.WARNING,
            profiles=("default",),
            element=ElementKind.FIELD,
            message_template="m",
        )
        def raising_rule(_ctx: Any) -> None:
            raise ValueError("bang")

        good = _decorated_field_rule("good/rule")
        engine = LintEngine()
        engine.load_rule_pack(_make_pack("fail_pack", (raising_rule, good)))
        report = engine.run(
            result,
            profile=LintProfile(
                name="x",
                rule_ids=frozenset({"bad/value", "good/rule"}),
                min_severity=LintSeverity.INFO,
            ),
        )
        # Walk completed; good rule findings present.
        assert any(f.rule_id == "good/rule" for f in report.findings)
        # Each ValueError emitted one runtime warning per field visit (3 fields).
        rule_excs = [
            w for w in report.runtime_warnings
            if w.category == "rule_exception" and w.rule_id == "bad/value"
        ]
        assert len(rule_excs) >= 1
        assert all(w.exception_type == "ValueError" for w in rule_excs)
        assert all(w.descriptor_path is not None for w in rule_excs)

    def test_system_exit_caught_at_rule_boundary(
        self, tmp_path: Path,
    ) -> None:
        """SystemExit MUST be caught — D2 R16 amendment.

        Without the catch, ``sys.exit(1)`` from a rule would terminate
        the test process. This test runs the engine and asserts
        ``engine.run`` returned with the warning recorded.
        """
        result = _compile(tmp_path, {"types.proto": _TWO_MSG_PROTO})

        @lint_rule(
            rule_id="bad/exit",
            severity=LintSeverity.WARNING,
            profiles=("default",),
            element=ElementKind.FIELD,
            message_template="m",
        )
        def exiting_rule(_ctx: Any) -> None:
            raise SystemExit(1)

        engine = LintEngine()
        engine.load_rule_pack(_make_pack("exit_pack", (exiting_rule,)))
        report = engine.run(
            result,
            profile=LintProfile(
                name="x", rule_ids=frozenset({"bad/exit"}),
                min_severity=LintSeverity.INFO,
            ),
        )
        # Engine returned normally; SystemExit captured as a runtime warning.
        sys_exits = [
            w for w in report.runtime_warnings
            if w.exception_type == "SystemExit"
        ]
        assert len(sys_exits) >= 1
        assert all(w.category == "rule_exception" for w in sys_exits)

    def test_memory_error_propagates_uncaught(self, tmp_path: Path) -> None:
        """MemoryError is NOT in the catch tuple — propagates."""
        result = _compile(tmp_path, {"types.proto": _TWO_MSG_PROTO})

        @lint_rule(
            rule_id="bad/oom",
            severity=LintSeverity.WARNING,
            profiles=("default",),
            element=ElementKind.FIELD,
            message_template="m",
        )
        def oom_rule(_ctx: Any) -> None:
            raise MemoryError("simulated OOM")

        engine = LintEngine()
        engine.load_rule_pack(_make_pack("oom_pack", (oom_rule,)))
        with pytest.raises(MemoryError):
            engine.run(
                result,
                profile=LintProfile(
                    name="x", rule_ids=frozenset({"bad/oom"}),
                    min_severity=LintSeverity.INFO,
                ),
            )

    def test_lint_rule_error_caught_records_runtime_warning(
        self, tmp_path: Path,
    ) -> None:
        result = _compile(tmp_path, {"types.proto": _TWO_MSG_PROTO})

        @lint_rule(
            rule_id="bad/soft",
            severity=LintSeverity.WARNING,
            profiles=("default",),
            element=ElementKind.FIELD,
            message_template="m",
        )
        def soft_rule(_ctx: Any) -> None:
            raise LintRuleError("rule explicitly bailed")

        engine = LintEngine()
        engine.load_rule_pack(_make_pack("soft_pack", (soft_rule,)))
        report = engine.run(
            result,
            profile=LintProfile(
                name="x", rule_ids=frozenset({"bad/soft"}),
                min_severity=LintSeverity.INFO,
            ),
        )
        soft_excs = [
            w for w in report.runtime_warnings
            if w.exception_type == "LintRuleError"
        ]
        assert len(soft_excs) >= 1


# ---------------------------------------------------------------------------
# Run: compile diagnostics passthrough
# ---------------------------------------------------------------------------


class TestCompileDiagnosticsPassthrough:
    """LintReport.diagnostics mirrors compile_result.diagnostics verbatim."""

    def test_diagnostics_passed_through(self, tmp_path: Path) -> None:
        result = _compile(tmp_path, {"types.proto": _TWO_MSG_PROTO})
        # Inject a fake compile diagnostic by replacing the field on the
        # frozen dataclass (it's frozen so we use object.__setattr__).
        diag = LintCompileDiagnostic(
            level="info",
            message="manual fixture",
        )
        object.__setattr__(result, "diagnostics", (diag,))

        engine = LintEngine()
        report = engine.run(
            result,
            profile=LintProfile(name="x", rule_ids=frozenset(),
                                min_severity=LintSeverity.INFO),
        )
        assert report.diagnostics == (diag,)
