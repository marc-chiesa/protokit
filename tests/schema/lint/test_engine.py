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
from google.protobuf import descriptor_pb2, descriptor_pool

from protokit.schema.compile import (
    CompileResult,
    LintCompileDiagnostic,
    compile_protos_to_result,
)
from protokit.schema.lint.decorator import lint_rule
from protokit.schema.lint.engine import (
    _RULE_EXCEPTION_TUPLE,
    LintEngine,
    _walk_cycle_forward,
)
from protokit.schema.lint.model import (
    DuplicateRuleError,
    ElementKind,
    LintProfile,
    LintRuleError,
    LintRuleSpec,
    LintSeverity,
)
from protokit.schema.lint.rules import BUILTIN_PACKS

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

    def test_has_rules_false_before_load_true_after(self) -> None:
        rule_a = _decorated_field_rule("hr/one")
        pack = _make_pack("pack_has_rules", (rule_a,))
        engine = LintEngine()
        assert not engine.has_rules
        engine.load_rule_pack(pack)
        assert engine.has_rules


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
# Run: LintReport.specs population (D3 substrate for formatter spec access)
# ---------------------------------------------------------------------------


class TestRunPopulatesSpecs:
    """Engine populates ``LintReport.specs`` from ``self._loaded_specs``.

    The field exists so formatters can render messages from
    ``LintRuleSpec.message_template`` without reaching back into
    engine internals — critical for D3's human formatter and D4's
    machine formatters.
    """

    def test_run_populates_specs_with_every_loaded_spec(
        self, tmp_path: Path,
    ) -> None:
        result = _compile(tmp_path, {"types.proto": _TWO_MSG_PROTO})
        rule_a = _decorated_field_rule("pack/rule-a")
        rule_b = _decorated_field_rule("pack/rule-b")
        engine = LintEngine()
        engine.load_rule_pack(_make_pack("test_pack", (rule_a, rule_b)))
        report = engine.run(
            result,
            profile=LintProfile(
                name="x",
                rule_ids=frozenset({"pack/rule-a", "pack/rule-b"}),
                min_severity=LintSeverity.INFO,
            ),
        )
        # Every loaded rule is in specs, keyed by rule_id
        assert set(report.specs.keys()) == {"pack/rule-a", "pack/rule-b"}
        # Each value is the actual LintRuleSpec
        assert report.specs["pack/rule-a"].rule_id == "pack/rule-a"
        assert report.specs["pack/rule-b"].rule_id == "pack/rule-b"

    def test_specs_contains_inactive_rules_too(
        self, tmp_path: Path,
    ) -> None:
        # Specs is the LOADED registry, not the active subset. A rule
        # that's loaded but not in the profile's rule_ids still
        # appears in specs (the divergence is documented in
        # LintReport.specs's docstring). This matters for D5+ where
        # pyproject config may want to introspect available rules.
        result = _compile(tmp_path, {"types.proto": _TWO_MSG_PROTO})
        active = _decorated_field_rule("pack/active")
        inactive = _decorated_field_rule("pack/inactive")
        engine = LintEngine()
        engine.load_rule_pack(_make_pack("test_pack", (active, inactive)))
        report = engine.run(
            result,
            profile=LintProfile(
                name="x",
                rule_ids=frozenset({"pack/active"}),  # only active
                min_severity=LintSeverity.INFO,
            ),
        )
        # Both loaded rules are in specs
        assert set(report.specs.keys()) == {"pack/active", "pack/inactive"}
        # But only the active one is in rules_run
        assert set(report.rules_run) == {"pack/active"}

    def test_specs_isolated_from_engine_loaded_specs(
        self, tmp_path: Path,
    ) -> None:
        # Defensive snapshot: __post_init__ does dict(self.specs) so
        # post-construction mutation of the engine's _loaded_specs
        # MUST NOT affect the report. This is the load-bearing
        # immutability claim for cached / replayed reports.
        result = _compile(tmp_path, {"types.proto": _TWO_MSG_PROTO})
        rule = _decorated_field_rule("pack/rule")
        engine = LintEngine()
        engine.load_rule_pack(_make_pack("test_pack", (rule,)))
        report = engine.run(
            result,
            profile=LintProfile(
                name="x",
                rule_ids=frozenset({"pack/rule"}),
                min_severity=LintSeverity.INFO,
            ),
        )
        snapshot = set(report.specs.keys())
        # Mutate the engine's registry post-run
        engine._loaded_specs.clear()
        # Report's view is unchanged
        assert set(report.specs.keys()) == snapshot

    def test_empty_engine_produces_empty_specs(
        self, tmp_path: Path,
    ) -> None:
        result = _compile(tmp_path, {"types.proto": _TWO_MSG_PROTO})
        engine = LintEngine()  # no rule pack loaded
        report = engine.run(
            result,
            profile=LintProfile(
                name="x",
                rule_ids=frozenset(),
                min_severity=LintSeverity.INFO,
            ),
        )
        assert dict(report.specs) == {}

    def test_specs_is_immutable_post_construction(
        self, tmp_path: Path,
    ) -> None:
        # ``LintReport.specs`` wraps the snapshot in ``MappingProxyType``
        # (``__post_init__``) so post-construction mutation raises
        # TypeError. Matches the immutability guarantee of sibling
        # tuple fields (findings, runtime_warnings).
        result = _compile(tmp_path, {"types.proto": _TWO_MSG_PROTO})
        rule = _decorated_field_rule("pack/rule")
        engine = LintEngine()
        engine.load_rule_pack(_make_pack("test_pack", (rule,)))
        report = engine.run(
            result,
            profile=LintProfile(
                name="x",
                rule_ids=frozenset({"pack/rule"}),
                min_severity=LintSeverity.INFO,
            ),
        )
        with pytest.raises(TypeError):
            report.specs["new_rule"] = None  # type: ignore[index]
        with pytest.raises(TypeError):
            del report.specs["pack/rule"]  # type: ignore[attr-defined]


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

    def test_rule_exception_tuple_pinned_to_documented_seven(self) -> None:
        """AC-06 structural pin: ``_RULE_EXCEPTION_TUPLE`` is exactly 7 items.

        ``LintRuleError.__doc__`` claims the catch tuple "is exactly"
        ``(SystemExit, ValueError, TypeError, AttributeError, LookupError,
        DecodeError, LintRuleError)``. A future engine delivery that
        adds an 8th exception class to the tuple MUST also update the
        docstring in the same commit; this pin trips otherwise. Lives
        next to ``_RULE_EXCEPTION_TUPLE`` in ``test_engine.py`` (the
        engine symbol's home test module) so renames trip the test
        adjacent to the rename rather than across modules. The
        companion docstring-wording test lives in ``test_model.py``
        next to ``LintRuleError``.

        D6d U2 ce:review added ``google.protobuf.message.DecodeError``
        as the seventh item to cover the dynamic-pool re-parse pattern
        used by option-aware rules (``MergeFromString`` on serialized
        options bytes can raise ``DecodeError`` on corrupted bytes;
        before the addition, the exception would have crashed
        ``engine.run()`` instead of being recorded as a
        ``rule_exception`` warning).
        """
        from google.protobuf.message import DecodeError

        assert (
            SystemExit,
            ValueError,
            TypeError,
            AttributeError,
            LookupError,
            DecodeError,
            LintRuleError,
        ) == _RULE_EXCEPTION_TUPLE

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

        Test design note: a rule that raises ``SystemExit`` directly
        is equivalent to one that calls ``sys.exit()`` — both raise
        the same exception. The plan suggested subprocess-based
        verification to avoid pytest's own SystemExit handling, but
        the in-process test is sufficient because the assertion
        below (``engine.run returned``) only succeeds if the engine
        caught the SystemExit. If the catch were absent, the
        SystemExit would unwind out of ``engine.run`` and pytest
        would report the test as ``ERROR`` (uncaught BaseException),
        not as ``PASSED``. The behavior is observably distinct
        without subprocess overhead.

        For the subprocess discipline (verifying the calling-process
        exit code is unchanged), see the parallel test at
        ``test_system_exit_does_not_terminate_test_process`` below.
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
        # Three FIELD descriptors (z_field/m_field/a_field) → three SystemExit
        # warnings. Strict count proves the walk wasn't aborted partway.
        assert len(sys_exits) == 3
        assert all(w.category == "rule_exception" for w in sys_exits)
        # Sanity-check this assertion line is reached — proves the test
        # process is still alive, complementing the runtime_warning check.
        assert engine._current_profile is None

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

    def test_diagnostics_snapshot_stable_under_mid_walk_mutation(
        self, tmp_path: Path,
    ) -> None:
        """Rule mid-walk mutation of compile_result.diagnostics is invisible to report.

        Engine snapshots ``compile_result.diagnostics`` at ``run()``
        entry into a local tuple — subsequent mutation of the source
        field does not change what the report carries. Closes the
        plan's TG6 gap.
        """
        result = _compile(tmp_path, {"types.proto": _TWO_MSG_PROTO})
        original = LintCompileDiagnostic(level="info", message="original")
        object.__setattr__(result, "diagnostics", (original,))
        captured: list[LintCompileDiagnostic] = []

        @lint_rule(
            rule_id="mut/diag",
            severity=LintSeverity.WARNING,
            profiles=("default",),
            element=ElementKind.FIELD,
            message_template="m",
        )
        def mutate_diagnostics(_ctx: Any) -> None:
            replacement = LintCompileDiagnostic(level="error", message="mutated")
            captured.append(replacement)
            # Replace the field on the frozen dataclass mid-walk.
            object.__setattr__(result, "diagnostics", (replacement,))

        engine = LintEngine()
        engine.load_rule_pack(_make_pack("diag_mut_pack", (mutate_diagnostics,)))
        report = engine.run(
            result,
            profile=LintProfile(
                name="x", rule_ids=frozenset({"mut/diag"}),
                min_severity=LintSeverity.INFO,
            ),
        )
        # The rule successfully mutated compile_result.diagnostics:
        assert result.diagnostics == (captured[0],)
        # But the report still carries the snapshot from run() entry:
        assert report.diagnostics == (original,)


# ---------------------------------------------------------------------------
# Reentrancy + lifetime guards (added per ce:review fixes)
# ---------------------------------------------------------------------------


class TestReentrancyAndLifetime:
    """Engine raises on nested run() and on emit() outside an active run."""

    def test_run_raises_on_reentrant_call_from_rule_callable(
        self, tmp_path: Path,
    ) -> None:
        """A rule that calls engine.run() recursively triggers RuntimeError."""
        result = _compile(tmp_path, {"types.proto": _TWO_MSG_PROTO})
        engine = LintEngine()
        observed: list[BaseException] = []

        @lint_rule(
            rule_id="reenter/x",
            severity=LintSeverity.WARNING,
            profiles=("default",),
            element=ElementKind.FIELD,
            message_template="m",
        )
        def reentrant_rule(_ctx: Any) -> None:
            try:
                engine.run(
                    result,
                    profile=LintProfile(
                        name="inner",
                        rule_ids=frozenset({"reenter/x"}),
                        min_severity=LintSeverity.INFO,
                    ),
                )
            except RuntimeError as exc:
                observed.append(exc)
                # Re-raise to surface in runtime_warnings (RuntimeError is
                # NOT in _RULE_EXCEPTION_TUPLE, so this would tear down
                # the outer run if not caught here).
                raise

        engine.load_rule_pack(_make_pack("reenter_pack", (reentrant_rule,)))
        # The outer run propagates the RuntimeError because RuntimeError
        # is not in the catch tuple.
        with pytest.raises(RuntimeError, match="not reentrant"):
            engine.run(
                result,
                profile=LintProfile(
                    name="outer",
                    rule_ids=frozenset({"reenter/x"}),
                    min_severity=LintSeverity.INFO,
                ),
            )
        assert len(observed) >= 1
        assert "not reentrant" in str(observed[0])

    def test_run_clears_current_profile_in_finally(
        self, tmp_path: Path,
    ) -> None:
        """After run() raises mid-walk, _current_profile is None for next run."""
        result = _compile(tmp_path, {"types.proto": _TWO_MSG_PROTO})
        engine = LintEngine()

        @lint_rule(
            rule_id="oom/x",
            severity=LintSeverity.WARNING,
            profiles=("default",),
            element=ElementKind.FIELD,
            message_template="m",
        )
        def memerr(_ctx: Any) -> None:
            raise MemoryError("simulated")

        engine.load_rule_pack(_make_pack("memerr_pack", (memerr,)))
        with pytest.raises(MemoryError):
            engine.run(
                result,
                profile=LintProfile(
                    name="x", rule_ids=frozenset({"oom/x"}),
                    min_severity=LintSeverity.INFO,
                ),
            )
        # After the propagating exception, _current_profile must be None
        # so the next run() doesn't trip the reentrancy guard.
        assert engine._current_profile is None
        # ce:review follow-up (Finding #6 / Testing T-3): every per-run
        # snapshot field in the finally block must be cleared
        # independently. _current_source_info_descriptors (D6b U1/U2) +
        # _current_package_options (D6b U4a) +
        # _current_directory_packages (D6c U1) all alias compile_result
        # state; a missing clear leaks across run() invocations.
        assert engine._current_source_info_descriptors is None
        assert engine._current_package_options is None
        assert engine._current_directory_packages is None
        # A subsequent normal run must work.
        report = engine.run(
            result,
            profile=LintProfile(
                name="x", rule_ids=frozenset(),
                min_severity=LintSeverity.INFO,
            ),
        )
        assert report.findings == ()

    def test_emit_after_run_raises_runtimeerror(
        self, tmp_path: Path,
    ) -> None:
        """A captured ctx that emit()s after run() returns hits the lifetime guard."""
        result = _compile(tmp_path, {"types.proto": _TWO_MSG_PROTO})
        engine = LintEngine()
        captured_ctxs: list[Any] = []

        @lint_rule(
            rule_id="capture/ctx",
            severity=LintSeverity.WARNING,
            profiles=("default",),
            element=ElementKind.FIELD,
            message_template="m",
        )
        def capture_ctx(ctx: Any) -> None:
            captured_ctxs.append(ctx)

        engine.load_rule_pack(_make_pack("capture_pack", (capture_ctx,)))
        engine.run(
            result,
            profile=LintProfile(
                name="x", rule_ids=frozenset({"capture/ctx"}),
                min_severity=LintSeverity.INFO,
            ),
        )
        # ctx escaped the run; calling emit() now must raise RuntimeError
        # (not silently corrupt the next run's accumulators).
        assert len(captured_ctxs) >= 1
        with pytest.raises(RuntimeError, match="outside of an active run"):
            captured_ctxs[0].emit(violation_kind="capture/ctx")


# ---------------------------------------------------------------------------
# Walk-order tie-break + uncaught-propagation positive tests (TG3, TG4, TG1)
# ---------------------------------------------------------------------------


_AMBIGUOUS_PACKAGE_FILE_A = """
syntax = "proto3";
package empty;

message Foo {
  string a_field = 1;
}
"""


_AMBIGUOUS_PACKAGE_FILE_B = """
syntax = "proto3";
package empty;

message Foo {
  string b_field = 1;
}
"""


class TestWalkOrderTieBreak:
    """Per-level full_name sort tie-break by file basename (TG3)."""

    def test_ambiguous_full_name_tie_breaks_by_file_basename(
        self, tmp_path: Path,
    ) -> None:
        """Two files declaring the same full_name (empty.Foo) sort by file basename."""
        # NOTE: protobuf forbids two files in the same pool from declaring
        # the same fully-qualified message name. Use different basenames
        # but identical package + message names — the pool will reject the
        # second .Add() with TypeError. So we test the tie-break logic at
        # the engine sort level using a two-MESSAGE fixture in one file
        # where both messages happen to have full_name collisions
        # (impossible in proto3) — instead we test that the sort key is
        # stable when given inputs with identical primary keys via
        # introspection of the helper directly.
        from types import SimpleNamespace

        items = [
            SimpleNamespace(full_name="empty.Foo", name="z_second.proto"),
            SimpleNamespace(full_name="empty.Foo", name="a_first.proto"),
        ]
        sorted_items = LintEngine._sorted_by_full_name(items)
        # Tie-break is on .name (the secondary key).
        assert sorted_items[0].name == "a_first.proto"
        assert sorted_items[1].name == "z_second.proto"


class TestUncaughtPropagation:
    """Positive tests that BaseException-but-not-Exception types propagate (TG1, TG4)."""

    def test_assertion_error_propagates_uncaught(self, tmp_path: Path) -> None:
        result = _compile(tmp_path, {"types.proto": _TWO_MSG_PROTO})

        @lint_rule(
            rule_id="bad/assert",
            severity=LintSeverity.WARNING,
            profiles=("default",),
            element=ElementKind.FIELD,
            message_template="m",
        )
        def assert_rule(_ctx: Any) -> None:
            raise AssertionError("invariant violated")

        engine = LintEngine()
        engine.load_rule_pack(_make_pack("assert_pack", (assert_rule,)))
        with pytest.raises(AssertionError):
            engine.run(
                result,
                profile=LintProfile(
                    name="x", rule_ids=frozenset({"bad/assert"}),
                    min_severity=LintSeverity.INFO,
                ),
            )

    def test_generator_exit_propagates_uncaught(self, tmp_path: Path) -> None:
        """GeneratorExit is BaseException-but-not-Exception; engine must not catch it."""
        result = _compile(tmp_path, {"types.proto": _TWO_MSG_PROTO})

        @lint_rule(
            rule_id="bad/genexit",
            severity=LintSeverity.WARNING,
            profiles=("default",),
            element=ElementKind.FIELD,
            message_template="m",
        )
        def genexit_rule(_ctx: Any) -> None:
            raise GeneratorExit("simulated")

        engine = LintEngine()
        engine.load_rule_pack(_make_pack("genexit_pack", (genexit_rule,)))
        with pytest.raises(GeneratorExit):
            engine.run(
                result,
                profile=LintProfile(
                    name="x", rule_ids=frozenset({"bad/genexit"}),
                    min_severity=LintSeverity.INFO,
                ),
            )


# ---------------------------------------------------------------------------
# Empty root_files combined with unloaded rule (TG2) + reload contract (TG5)
# ---------------------------------------------------------------------------


class TestEmptyRootFilesUnloadedRuleCombined:
    """Unloaded-rule diff must precede the walk; empty root_files still emits."""

    def test_empty_root_files_with_unloaded_rule_emits_warning(self) -> None:
        from google.protobuf import descriptor_pool

        from protokit.schema.compile import CompileResult

        empty = CompileResult(
            pool=descriptor_pool.DescriptorPool(),
            root_files=(),
            diagnostics=(),
        )
        engine = LintEngine()
        report = engine.run(
            empty,
            profile=LintProfile(
                name="x",
                rule_ids=frozenset({"missing/rule"}),
                min_severity=LintSeverity.INFO,
            ),
        )
        # Walk produced nothing, but unloaded-rule diff still fired.
        assert report.findings == ()
        unloaded = [
            w for w in report.runtime_warnings if w.category == "unloaded_rule"
        ]
        assert len(unloaded) == 1
        assert unloaded[0].rule_id == "missing/rule"


class TestReloadContract:
    """importlib.reload + engine.reset + load_rule_pack picks up fresh specs (TG5)."""

    def test_reset_then_reload_picks_up_module_changes(
        self, tmp_path: Path,
    ) -> None:
        """After engine.reset() + module mutation + load_rule_pack again, fresh specs are used."""
        # Simulate a "reload" by mutating a synthetic pack module's RULES
        # tuple in place between two load_rule_pack calls (separated by
        # engine.reset()).
        rule_v1 = _decorated_field_rule("reload/x", severity=LintSeverity.INFO)
        rule_v2 = _decorated_field_rule("reload/x", severity=LintSeverity.ERROR)
        pack = _make_pack("reload_pack", (rule_v1,))

        engine = LintEngine()
        engine.load_rule_pack(pack)
        assert engine._loaded_specs["reload/x"].severity is LintSeverity.INFO

        # "Reload" — reset engine, swap RULES, load again.
        engine.reset()
        pack.RULES = (rule_v2,)
        engine.load_rule_pack(pack)
        assert engine._loaded_specs["reload/x"].severity is LintSeverity.ERROR


# ---------------------------------------------------------------------------
# Partial-pool tolerance — the defensive branches no test reached
# ---------------------------------------------------------------------------


class TestPartialPoolStateTolerance:
    """A ``CompileResult`` naming a root file absent from the pool must not crash.

    The engine's cross-file accumulators each look their root files up with
    ``FindFileByName`` inside ``try/except KeyError: continue``. Every one of
    those guards exists for a real state — a compile that failed partway leaves
    ``root_files`` naming a file the pool never received — and a mutation audit
    turned each ``continue`` into ``raise`` with the whole suite still green.
    Nothing had ever handed the engine an inconsistent result.

    Building the ``CompileResult`` directly is the only way to reach this:
    ``compile_protos_to_result`` cannot be made to emit a root file it did not
    put in the pool, which is precisely why the state went untested.
    """

    @staticmethod
    def _ghost_result() -> CompileResult:
        """A root file that is not in the pool — the compile-failure shape."""
        return CompileResult(
            pool=descriptor_pool.DescriptorPool(),
            root_files=("ghost.proto",),
            diagnostics=(),
        )

    @staticmethod
    def _engine_with_all_builtins() -> LintEngine:
        engine = LintEngine()
        for pack in BUILTIN_PACKS:
            engine.load_rule_pack(pack)
        return engine

    def test_missing_root_file_does_not_crash_the_run(self) -> None:
        engine = self._engine_with_all_builtins()
        rule_ids = frozenset(engine.loaded_rule_ids)

        report = engine.run(
            self._ghost_result(),
            profile=LintProfile(
                name="_test_partial_pool",
                rule_ids=rule_ids,
                min_severity=LintSeverity.INFO,
            ),
        )

        # The contract is tolerance, not silence: the file cannot be walked, so
        # it yields nothing, and the run still returns a report.
        assert report.findings == ()

    def test_a_present_file_is_still_linted_alongside_a_ghost(self) -> None:
        """Tolerance must skip the missing file only — not abandon the walk.

        A guard that swallowed too much would also pass the test above, since
        an empty report is what a fully-abandoned run produces too.
        """
        pool = descriptor_pool.DescriptorPool()
        fp = descriptor_pb2.FileDescriptorProto(
            name="real.proto", package="", syntax="proto3",
        )
        msg = fp.message_type.add()
        msg.name = "badName"  # violates naming/... to force a finding
        fld = msg.field.add()
        fld.name, fld.number = "BadField", 1
        fld.type, fld.label = fld.TYPE_STRING, fld.LABEL_OPTIONAL
        pool.Add(fp)

        engine = self._engine_with_all_builtins()
        report = engine.run(
            CompileResult(
                pool=pool,
                root_files=("ghost.proto", "real.proto"),
                diagnostics=(),
            ),
            profile=LintProfile(
                name="_test_partial_pool_mixed",
                rule_ids=frozenset(engine.loaded_rule_ids),
                min_severity=LintSeverity.INFO,
            ),
        )

        assert report.findings, "the present file must still be linted"
        assert all(f.location.file == "real.proto" for f in report.findings)


class TestPackageOptionsAccumulatorTolerance:
    """The options accumulator survives an option name protobuf does not know.

    Unlike the accumulators above, this one iterates ``pool_file_names`` rather
    than ``root_files``, so a ghost root file never reaches it and its guard
    stays untouched by the partial-pool fixture. Its real trigger is version
    skew: ``_PACKAGE_SAME_OPTION_ATTR_NAMES`` is a hard-coded list of
    ``FileOptions`` fields, and ``opts.HasField()`` raises ``ValueError`` for a
    name the installed protobuf does not have. A newer name in that list — or
    an older protobuf — must degrade to "no options data for this file", not
    abort the whole lint run.

    A mutation audit turned the guard's ``continue`` into ``raise`` and the
    suite stayed green, because nothing had ever fed it an unknown option name.
    """

    def test_unknown_option_name_does_not_abort_the_run(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from protokit.schema.lint.rules import package_same

        monkeypatch.setattr(
            package_same,
            "_PACKAGE_SAME_OPTION_ATTR_NAMES",
            ("java_package", "an_option_this_protobuf_does_not_have"),
        )

        pool = descriptor_pool.DescriptorPool()
        fp = descriptor_pb2.FileDescriptorProto(
            name="opt.proto", package="t", syntax="proto3",
        )
        msg = fp.message_type.add()
        msg.name = "M"
        fld = msg.field.add()
        fld.name, fld.number = "a", 1
        fld.type, fld.label = fld.TYPE_STRING, fld.LABEL_OPTIONAL
        pool.Add(fp)

        engine = LintEngine()
        for pack in BUILTIN_PACKS:
            engine.load_rule_pack(pack)

        report = engine.run(
            CompileResult(
                pool=pool,
                root_files=("opt.proto",),
                # This accumulator iterates the POOL, not root_files, so the
                # pool listing is what has to be populated to reach it.
                pool_file_names=("opt.proto",),
                diagnostics=(),
            ),
            profile=LintProfile(
                name="_test_option_skew",
                rule_ids=frozenset(engine.loaded_rule_ids),
                min_severity=LintSeverity.INFO,
            ),
        )

        # The run completed rather than raising; that is the whole contract.
        assert isinstance(report.findings, tuple)


class TestCycleWalkFallback:
    """``_walk_cycle_forward`` returns a usable path even on a caller mismatch.

    The fallback fires when the source package has no route back to itself
    inside the claimed SCC — impossible if the Tarjan analysis and the caller
    agree, which is why nothing exercised it. A mutation audit changed the
    fallback from ``(source_pkg,)`` to ``()`` and the suite stayed green; an
    empty tuple renders as an empty cycle path, so the finding a user sees
    would name no packages at all.
    """

    def test_no_route_back_still_names_the_source(self) -> None:
        """SCC membership claimed, but no edges exist to close a cycle."""
        assert _walk_cycle_forward({}, {"acme.a"}, "acme.a") == ("acme.a",)

    def test_dead_end_edge_still_names_the_source(self) -> None:
        """Edges exist but lead nowhere back — the backtracking path."""
        result = _walk_cycle_forward(
            {"acme.a": {"acme.b"}, "acme.b": set()},
            {"acme.a", "acme.b"},
            "acme.a",
        )
        assert result == ("acme.a",)

    def test_a_real_cycle_is_still_walked(self) -> None:
        """Guards against a fallback that swallows the working path."""
        result = _walk_cycle_forward(
            {"acme.a": {"acme.b"}, "acme.b": {"acme.a"}},
            {"acme.a", "acme.b"},
            "acme.a",
        )
        assert result == ("acme.a", "acme.b", "acme.a")


class TestPlaceholderSpecDispatch:
    """``_invoke_rule`` returns quietly on a spec whose ``fn`` is ``None``.

    ``LintRuleSpec.fn`` is documented as ``None``-able for placeholder specs in
    tests, with production registration rejecting ``None``. That makes the
    guard reachable only from a test — and no test called it, so a mutation
    audit replaced the return with ``raise AssertionError`` and the suite stayed
    green. Without the guard a placeholder spec reaching dispatch crashes the
    engine instead of being skipped.
    """

    def test_none_fn_is_skipped_without_raising(self) -> None:
        engine = LintEngine()
        spec = LintRuleSpec(
            rule_id="placeholder/none-fn",
            severity=LintSeverity.WARNING,
            profiles=("default",),
            element=ElementKind.FIELD,
            message_template="unused",
            fn=None,
        )
        # A context is never touched on this path, so a sentinel proves it:
        # anything the guard failed to skip would raise on attribute access.
        engine._invoke_rule(spec, object())

    def test_a_real_fn_is_still_invoked(self) -> None:
        """Guards against a fix that skips every spec."""
        called: list[object] = []
        spec = LintRuleSpec(
            rule_id="placeholder/real-fn",
            severity=LintSeverity.WARNING,
            profiles=("default",),
            element=ElementKind.FIELD,
            message_template="unused",
            fn=lambda ctx: called.append(ctx),
        )
        LintEngine()._invoke_rule(spec, "ctx-sentinel")
        assert called == ["ctx-sentinel"]


class TestMissingDependencyTolerance:
    """The import graph skips a dependency the pool has lost.

    A descriptor pool always contains its files' dependencies — it refuses to
    add a file whose imports are not loaded — so this guard cannot be reached
    by building a pool the ordinary way, which is why a mutation audit turned
    its ``continue`` into ``raise`` with the suite green.

    A partial pool is exactly what it guards, though, so the test builds a real
    two-file pool and then wraps it to lose one: lookups behave normally except
    for the dependency, which raises ``KeyError`` the way a pool assembled from
    a truncated descriptor set would. Losing the guard turns that into a crash
    with no LintReport at all, rather than one file's edges going unmapped.
    """

    def test_unresolvable_dependency_does_not_abort_the_accumulator(
        self,
    ) -> None:
        pool = descriptor_pool.DescriptorPool()
        dep = descriptor_pb2.FileDescriptorProto(
            name="dep.proto", package="acme.dep", syntax="proto3",
        )
        dep_msg = dep.message_type.add()
        dep_msg.name = "D"
        pool.Add(dep)

        root = descriptor_pb2.FileDescriptorProto(
            name="root.proto", package="acme.root", syntax="proto3",
        )
        root.dependency.append("dep.proto")
        root_msg = root.message_type.add()
        root_msg.name = "R"
        fld = root_msg.field.add()
        fld.name, fld.number = "d", 1
        fld.type, fld.label = fld.TYPE_MESSAGE, fld.LABEL_OPTIONAL
        fld.type_name = ".acme.dep.D"
        pool.Add(root)

        class _PoolMissingTheDependency:
            """Real pool, minus one file — the truncated-input shape."""

            @staticmethod
            def FindFileByName(name: str):  # noqa: N802, ANN205 - protobuf API
                if name == "dep.proto":
                    raise KeyError(name)
                return pool.FindFileByName(name)

        result = CompileResult(
            pool=_PoolMissingTheDependency(),  # type: ignore[arg-type]
            root_files=("root.proto",),
            pool_file_names=("root.proto",),
            diagnostics=(),
        )

        # The contract is that this returns rather than raising. The lost
        # dependency simply contributes no package edge.
        accumulator = LintEngine()._build_import_graph_accumulator(result)
        assert accumulator is None or "root.proto" not in accumulator
