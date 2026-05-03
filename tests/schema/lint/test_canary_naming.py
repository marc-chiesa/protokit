"""Tests for the ``naming/snake-case-fields`` canary rule pack.

Cover the regex semantics, map-entry skip, RULES module shape, and
end-to-end integration with the engine through real proto fixtures.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from protokit.schema.compile import compile_protos_to_result
from protokit.schema.lint.engine import LintEngine
from protokit.schema.lint.model import ElementKind, LintProfile, LintSeverity
from protokit.schema.lint.rules import naming as naming_pack
from protokit.schema.lint.rules.naming import (
    RULES,
    check_snake_case_fields,
)


def _compile(tmp_path: Path, sources: dict[str, str]) -> Any:
    paths: list[Path] = []
    for fname, text in sources.items():
        p = tmp_path / fname
        p.write_text(text)
        paths.append(p)
    return compile_protos_to_result(paths=paths, proto_paths=(str(tmp_path),))


# ---------------------------------------------------------------------------
# Module shape — RULES tuple + spec metadata
# ---------------------------------------------------------------------------


class TestNamingPackShape:
    """The naming pack exposes RULES with the canary rule properly registered."""

    def test_rules_attribute_is_tuple_of_decorated_fns(self) -> None:
        """RULES is a tuple containing the decorated check_snake_case_fields fn."""
        assert isinstance(RULES, tuple)
        assert (check_snake_case_fields,) == RULES
        for fn in RULES:
            assert hasattr(fn, "_lint_spec")

    def test_canary_spec_metadata_matches_aip_122(self) -> None:
        """The canary spec carries the documented metadata."""
        spec = check_snake_case_fields._lint_spec  # type: ignore[attr-defined]
        assert spec.rule_id == "naming/snake-case-fields"
        assert spec.severity is LintSeverity.WARNING
        assert spec.profiles == ("default",)
        assert spec.element is ElementKind.FIELD
        assert "snake_case" in spec.message_template
        assert spec.source_spec == "https://google.aip.dev/122"


# ---------------------------------------------------------------------------
# Engine integration — happy / sad / map-entry / from_pack
# ---------------------------------------------------------------------------


_ALL_GOOD_PROTO = """
syntax = "proto3";
package good;

message User {
  string good_name = 1;
  string also_fine = 2;
  string field_2_name = 3;
}
"""


# Bad-name fixture for the canary's sad-path tests.
#
# Note on exclusions:
# - ``_leading_underscore`` and ``with-dash`` are excluded because the
#   protobuf grammar rejects them at parse time — including either in
#   the fixture causes ``compile_protos_to_result`` to fail before the
#   engine sees a descriptor, which makes the canary's regex branches
#   for those cases dead code in practice. The regex still rejects
#   them defensively (per the docstring on ``_SNAKE_CASE_RE``); we
#   trust that branch via spec inspection rather than fixture testing.
_ALL_BAD_PROTO = """
syntax = "proto3";
package bad;

message User {
  string BadCamelCase = 1;
  string with__double = 2;
  string trailing_ = 3;
  string UPPER = 4;
}
"""


_MIXED_WITH_MAP_PROTO = """
syntax = "proto3";
package mixed;

message Settings {
  // user-authored field name — IS linted (snake_case so passes)
  map<string, string> attributes = 1;
  // user-authored field name with bad casing — fires
  string BadField = 2;
}
"""


def _run_canary(tmp_path: Path, sources: dict[str, str]) -> Any:
    """Compile sources, register the canary pack, run engine, return report."""
    result = _compile(tmp_path, sources)
    engine = LintEngine()
    engine.load_rule_pack(naming_pack)
    profile = LintProfile(
        name="default",
        rule_ids=frozenset({"naming/snake-case-fields"}),
        min_severity=LintSeverity.INFO,
    )
    return engine.run(result, profile=profile)


class TestCanaryHappyPath:
    """No findings on well-named fields."""

    def test_all_snake_case_fields_produce_no_findings(
        self, tmp_path: Path,
    ) -> None:
        report = _run_canary(tmp_path, {"good.proto": _ALL_GOOD_PROTO})
        assert report.findings == ()


class TestCanarySadPath:
    """Findings fire on AIP-122 violators."""

    def test_bad_names_produce_one_finding_each(self, tmp_path: Path) -> None:
        report = _run_canary(tmp_path, {"bad.proto": _ALL_BAD_PROTO})
        bad_names = {
            f.params["name"]
            for f in report.findings
            if f.rule_id == "naming/snake-case-fields"
        }
        assert bad_names == {
            "BadCamelCase",
            "with__double",
            "trailing_",
            "UPPER",
        }


class TestCanaryMapEntrySkip:
    """Synthetic key/value fields inside MapEntry messages are skipped."""

    def test_map_entry_synthetic_fields_skipped(self, tmp_path: Path) -> None:
        report = _run_canary(tmp_path, {"mixed.proto": _MIXED_WITH_MAP_PROTO})
        names = {f.params["name"] for f in report.findings}
        # The user-authored bad field fires.
        assert "BadField" in names
        # The synthetic key/value inside SettingsAttributesEntry must NOT fire.
        assert "key" not in names
        assert "value" not in names


# ---------------------------------------------------------------------------
# LintProfile.from_pack derivation
# ---------------------------------------------------------------------------


class TestCanaryFromPack:
    """LintProfile.from_pack walks the canary's RULES and derives a profile."""

    def test_from_pack_default_profile_includes_canary(self) -> None:
        profile = LintProfile.from_pack(naming_pack, "default")
        assert profile.name == "default"
        assert profile.rule_ids == frozenset({"naming/snake-case-fields"})

    def test_from_pack_unknown_profile_returns_empty(self) -> None:
        profile = LintProfile.from_pack(naming_pack, "nonexistent")
        assert profile.rule_ids == frozenset()
