"""Per-`ElementKind` walk coverage + cross-file boundary + integration tests.

Covers the success criteria the prior unit tests can't reach:

* Eight synthetic always-fires rules — one per ``ElementKind`` —
  registered into a throwaway test module and run against
  ``fixtures/all_kinds.proto``. Asserts each kind fires exactly the
  expected number of times AND that the silent-zero-output guard
  (``len(findings) + filtered_count >= expected_emit_count``) holds
  per the matcher-skew learning.
* Cross-file boundary: root A imports vendored C; the canary fires
  only on A's bad-name fields, never on C's, even when rules call
  ``ctx.pool.FindFileByName("c.proto")`` for cross-file lookups.
* Severity-override + filtered_count integration test using the
  REAL canary rule (not a synthetic). Distinguishes from Unit 3's
  synthetic-rule test by exercising the registered rule pack path.
* ``LintProfile.from_pack`` against the canary pack (smoke).
"""

from __future__ import annotations

import types
from pathlib import Path
from typing import Any

from protokit.schema.compile import compile_protos_to_result
from protokit.schema.lint.decorator import lint_rule
from protokit.schema.lint.engine import LintEngine
from protokit.schema.lint.model import ElementKind, LintProfile, LintSeverity
from protokit.schema.lint.rules import naming as naming_pack

_FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pack(name: str, fns: tuple[Any, ...]) -> types.ModuleType:
    """Throwaway rule pack module — name + RULES = fns."""
    mod = types.ModuleType(name)
    mod.RULES = fns
    return mod


def _compile_inline(tmp_path: Path, sources: dict[str, str]) -> Any:
    """Compile inline proto sources written to tmp_path."""
    paths: list[Path] = []
    for fname, text in sources.items():
        p = tmp_path / fname
        p.write_text(text)
        paths.append(p)
    return compile_protos_to_result(
        paths=paths, proto_paths=(str(tmp_path),),
    )


def _compile_all_kinds() -> Any:
    """Compile the checked-in fixture covering all 8 ElementKinds."""
    return compile_protos_to_result(
        paths=[_FIXTURES / "all_kinds.proto"],
        proto_paths=(str(_FIXTURES),),
    )


# ---------------------------------------------------------------------------
# Per-`ElementKind` walk coverage — 8 synthetic always-fires rules.
# ---------------------------------------------------------------------------


# Authoritative element counts in fixtures/all_kinds.proto:
#   FILE: 1, SERVICE: 1, METHOD: 1, ENUM: 2 (top-level + nested),
#   ENUM_VALUE: 4 (2 per enum), MESSAGE: 4 (3 top-level + 1 nested),
#   FIELD: 6 (incl. 2 oneof members), ONEOF: 1
_EXPECTED_COUNT_BY_KIND: dict[ElementKind, int] = {
    ElementKind.FILE: 1,
    ElementKind.SERVICE: 1,
    ElementKind.METHOD: 1,
    ElementKind.ENUM: 2,
    ElementKind.ENUM_VALUE: 4,
    ElementKind.MESSAGE: 4,
    ElementKind.FIELD: 6,
    ElementKind.ONEOF: 1,
}


def _make_always_fires_rule(kind: ElementKind) -> Any:
    """Synthetic rule that fires on every element of one ElementKind."""
    rule_id = f"walk/all-{kind.value}"

    @lint_rule(
        rule_id=rule_id,
        severity=LintSeverity.WARNING,
        profiles=("walk",),
        element=kind,
        message_template="emitted by " + rule_id,
    )
    def rule(ctx: Any) -> None:
        ctx.emit(violation_kind=rule_id)

    rule.__name__ = f"rule_walk_{kind.value}"
    return rule


class TestPerElementKindWalkCoverage:
    """All 8 synthetic rules fire the expected number of times."""

    def test_eight_synthetic_rules_fire_per_kind(self) -> None:
        result = _compile_all_kinds()
        rules = tuple(
            _make_always_fires_rule(kind) for kind in ElementKind
        )
        engine = LintEngine()
        engine.load_rule_pack(_make_pack("walk_coverage_pack", rules))
        rule_ids = frozenset(
            f"walk/all-{kind.value}" for kind in ElementKind
        )
        report = engine.run(
            result,
            profile=LintProfile(
                name="walk",
                rule_ids=rule_ids,
                min_severity=LintSeverity.INFO,
            ),
        )

        # Per-kind counts.
        actual_count_by_kind: dict[ElementKind, int] = {
            kind: 0 for kind in ElementKind
        }
        for finding in report.findings:
            # The rule_id format is "walk/all-{kind.value}" — recover.
            kind_str = finding.rule_id.removeprefix("walk/all-")
            kind = ElementKind(kind_str)
            actual_count_by_kind[kind] += 1
        assert actual_count_by_kind == _EXPECTED_COUNT_BY_KIND

        # Silent-zero-output guard (matcher-backend learning):
        # findings + filtered_count must reach the expected emit count.
        # Distinguishes "walk skipped elements" (both at 0) from
        # "filter dropped everything" (filtered_count == expected).
        expected_total = sum(_EXPECTED_COUNT_BY_KIND.values())
        assert len(report.findings) + report.filtered_count >= expected_total
        assert len(report.findings) > 0


# ---------------------------------------------------------------------------
# Cross-file boundary — root A imports vendored C
# ---------------------------------------------------------------------------


_ROOT_PROTO_TEXT = """
syntax = "proto3";
package root;
import "vendored.proto";

message A {
  vendored.C ref = 1;
  string BadField = 2;
}
"""

_VENDORED_PROTO_TEXT = """
syntax = "proto3";
package vendored;

message C {
  string c_BAD_field = 1;
}
"""


class TestCrossFileBoundary:
    """The canary fires only on root_files — never on imports."""

    def test_canary_skips_vendored_imports_even_with_cross_file_lookups(
        self, tmp_path: Path,
    ) -> None:
        # Compile only root.proto as a root; vendored.proto is import-only.
        p_root = tmp_path / "root.proto"
        p_vend = tmp_path / "vendored.proto"
        p_root.write_text(_ROOT_PROTO_TEXT)
        p_vend.write_text(_VENDORED_PROTO_TEXT)
        result = compile_protos_to_result(
            paths=[p_root], proto_paths=(str(tmp_path),),
        )
        assert "vendored.proto" not in result.root_files
        assert "root.proto" in result.root_files
        # Sanity-check: the cross-file lookup itself works (vendored.proto
        # IS in the pool). Rules in root.proto that call
        # ctx.pool.FindFileByName('vendored.proto') would succeed; the
        # engine just doesn't WALK it.
        assert result.pool.FindFileByName("vendored.proto") is not None

        engine = LintEngine()
        engine.load_rule_pack(naming_pack)
        report = engine.run(
            result,
            profile=LintProfile(
                name="default",
                rule_ids=frozenset({"naming/snake-case-fields"}),
                min_severity=LintSeverity.INFO,
            ),
        )
        # The canary should fire on root.proto's BadField only;
        # vendored.proto's c_BAD_field is reachable via pool but NOT walked.
        bad_files = {
            f.location.file  # type: ignore[attr-defined]
            for f in report.findings
        }
        assert bad_files == {"root.proto"}
        bad_names = {f.params["name"] for f in report.findings}
        assert "BadField" in bad_names
        assert "c_BAD_field" not in bad_names


# ---------------------------------------------------------------------------
# Severity override + filtered_count using the REAL canary
# ---------------------------------------------------------------------------


_BAD_FIELD_PROTO = """
syntax = "proto3";
package sev;

message Demo {
  string GoodFieldX = 1;
}
"""


class TestSeverityOverrideIntegrationWithCanary:
    """Real canary path: profile override + min_severity gate."""

    def test_canary_overridden_to_info_below_warning_gate_filters_out(
        self, tmp_path: Path,
    ) -> None:
        result = _compile_inline(tmp_path, {"sev.proto": _BAD_FIELD_PROTO})
        engine = LintEngine()
        engine.load_rule_pack(naming_pack)
        # Canary defaults to WARNING. Override to INFO; min_severity=WARNING.
        report = engine.run(
            result,
            profile=LintProfile(
                name="x",
                rule_ids=frozenset({"naming/snake-case-fields"}),
                min_severity=LintSeverity.WARNING,
                rule_severity_overrides={
                    "naming/snake-case-fields": LintSeverity.INFO,
                },
            ),
        )
        # GoodFieldX is bad; would emit one finding at default WARNING. The
        # override drops it to INFO and the min_severity=WARNING gate filters.
        assert report.findings == ()
        assert report.filtered_count == 1

    def test_canary_overridden_to_error_passes_gate_with_promoted_severity(
        self, tmp_path: Path,
    ) -> None:
        result = _compile_inline(tmp_path, {"sev.proto": _BAD_FIELD_PROTO})
        engine = LintEngine()
        engine.load_rule_pack(naming_pack)
        report = engine.run(
            result,
            profile=LintProfile(
                name="x",
                rule_ids=frozenset({"naming/snake-case-fields"}),
                min_severity=LintSeverity.WARNING,
                rule_severity_overrides={
                    "naming/snake-case-fields": LintSeverity.ERROR,
                },
            ),
        )
        # The override promotes the canary to ERROR; the gate passes.
        assert len(report.findings) == 1
        assert report.findings[0].severity is LintSeverity.ERROR


# ---------------------------------------------------------------------------
# from_pack against the real canary
# ---------------------------------------------------------------------------


class TestLintProfileFromPackWithCanary:
    """End-to-end derivation of a profile from the canary pack.

    D6a Unit 3 extended the naming pack with 8 additional rules and
    widened the canary's profile membership to
    ``("recommended", "default")``. The full set is covered by
    ``tests/schema/lint/rules/test_naming_extended.py``; this
    coverage just asserts the canary remains derived from the
    ``default`` profile.
    """

    def test_from_pack_default_yields_canary_rule_id(self) -> None:
        profile = LintProfile.from_pack(naming_pack, "default")
        assert "naming/snake-case-fields" in profile.rule_ids
