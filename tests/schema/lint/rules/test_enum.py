"""Tests for the D6a Unit 4 enum-semantics rule pack.

Covers the 2 rules registered in :mod:`protokit.schema.lint.rules.enum`:

- ``enum/no-allow-alias`` — fires whenever ``option allow_alias =
  true`` is set on an enum, including the structurally-necessary case
  (mirroring buf BASIC's ENUM_NO_ALLOW_ALIAS posture).
- ``enum/first-value-zero`` — fires when an enum's first declared
  value's number is not zero. Effectively unreachable on a
  successfully compiled proto3 enum (the grammar enforces zero); the
  sad-path test uses proto2 syntax where the grammar permits arbitrary
  first values.

Patterns mirror ``tests/schema/lint/rules/test_naming_extended.py``:
single-rule isolation profiles for per-rule sad-path tests, a
shared ``_compile`` helper, derived rule_id frozenset, and a
full-pack integration test.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from protokit.schema.compile import compile_protos_to_result
from protokit.schema.lint.engine import LintEngine
from protokit.schema.lint.model import ElementKind, LintProfile, LintSeverity
from protokit.schema.lint.rules import enum as enum_pack
from protokit.schema.lint.rules.enum import (
    RULES,
    check_first_value_zero,
    check_no_allow_alias,
)

# ---------------------------------------------------------------------------
# Shared compile + engine helpers
# ---------------------------------------------------------------------------


def _compile(
    tmp_path: Path,
    sources: dict[str, str],
) -> Any:
    """Write ``sources`` under ``tmp_path`` and compile them."""
    paths: list[Path] = []
    for fname, text in sources.items():
        p = tmp_path / fname
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        paths.append(p)
    return compile_protos_to_result(
        paths=paths,
        proto_paths=(str(tmp_path),),
    )


def _run_single(
    tmp_path: Path,
    sources: dict[str, str],
    rule_id: str,
) -> Any:
    """Run the engine with a profile containing only ``rule_id``."""
    result = _compile(tmp_path, sources)
    engine = LintEngine()
    engine.load_rule_pack(enum_pack)
    profile = LintProfile(
        name="default",
        rule_ids=frozenset({rule_id}),
        min_severity=LintSeverity.INFO,
    )
    return engine.run(result, profile=profile)


# ---------------------------------------------------------------------------
# Module shape — RULES tuple + spec metadata
# ---------------------------------------------------------------------------


class TestEnumPackShape:
    """The enum pack exposes RULES with both D6a Unit 4 rules registered."""

    def test_rules_tuple_contains_two_callables(self) -> None:
        assert isinstance(RULES, tuple)
        assert len(RULES) == 2
        for fn in RULES:
            assert hasattr(fn, "_lint_spec")

    def test_pack_includes_both_d6a_unit4_rules(self) -> None:
        assert check_no_allow_alias in RULES
        assert check_first_value_zero in RULES


class TestEnumRuleSpecs:
    """The 2 new rules carry the D6a Unit 4 spec metadata."""

    def test_no_allow_alias_spec(self) -> None:
        spec = check_no_allow_alias._lint_spec  # type: ignore[attr-defined]
        assert spec.rule_id == "enum/no-allow-alias"
        assert spec.severity is LintSeverity.ERROR
        assert spec.profiles == ("recommended", "default")
        assert spec.element is ElementKind.ENUM
        assert spec.source_spec == "buf:ENUM_NO_ALLOW_ALIAS"

    def test_first_value_zero_spec(self) -> None:
        spec = check_first_value_zero._lint_spec  # type: ignore[attr-defined]
        assert spec.rule_id == "enum/first-value-zero"
        assert spec.severity is LintSeverity.ERROR
        assert spec.profiles == ("recommended", "default")
        assert spec.element is ElementKind.ENUM
        assert spec.source_spec == "buf:ENUM_FIRST_VALUE_ZERO"


# ---------------------------------------------------------------------------
# enum/no-allow-alias
# ---------------------------------------------------------------------------


_NO_ALIAS_GOOD = """
syntax = "proto3";
package good;

enum Status {
  STATUS_UNSPECIFIED = 0;
  STATUS_ACTIVE = 1;
  STATUS_INACTIVE = 2;
}
"""

# Sad path: option set but no actual aliases. Mirrors buf — flag regardless.
_NO_ALIAS_BAD_NO_ACTUAL_ALIAS = """
syntax = "proto3";
package bad;

enum Status {
  option allow_alias = true;
  STATUS_UNSPECIFIED = 0;
  STATUS_ACTIVE = 1;
}
"""

# Sad path edge case: option is structurally needed (two values share
# number 0). The plan documents the diverge-or-mirror decision: buf
# flags this case anyway, and protokit mirrors to keep parity honest.
_NO_ALIAS_BAD_STRUCTURALLY_NEEDED = """
syntax = "proto3";
package bad;

enum Status {
  option allow_alias = true;
  STATUS_UNSPECIFIED = 0;
  STATUS_DISABLED = 0;
}
"""


class TestNoAllowAlias:
    """``enum/no-allow-alias`` fires whenever allow_alias is set."""

    def test_happy_path_no_allow_alias_clean(self, tmp_path: Path) -> None:
        report = _run_single(
            tmp_path,
            {"good.proto": _NO_ALIAS_GOOD},
            "enum/no-allow-alias",
        )
        assert report.findings == ()

    def test_sad_path_allow_alias_without_actual_alias_fires(
        self, tmp_path: Path,
    ) -> None:
        report = _run_single(
            tmp_path,
            {"bad.proto": _NO_ALIAS_BAD_NO_ACTUAL_ALIAS},
            "enum/no-allow-alias",
        )
        bad_enums = {f.params["name"] for f in report.findings}
        assert bad_enums == {"Status"}

    def test_sad_path_structurally_needed_alias_still_fires(
        self, tmp_path: Path,
    ) -> None:
        """Even when allow_alias IS structurally needed, the rule fires.

        Two values declared with the same number (0) require the
        option to compile cleanly, but buf BASIC's
        ENUM_NO_ALLOW_ALIAS treats the option as a design-smell
        signal regardless. Protokit mirrors to keep the parity
        claim ``source_spec="buf:ENUM_NO_ALLOW_ALIAS"`` honest at
        the rule-fires level. If a future delivery wants to
        distinguish "structurally needed" from "accidentally set",
        it would ship as a separate narrower rule rather than
        weakening this one.
        """
        report = _run_single(
            tmp_path,
            {"bad.proto": _NO_ALIAS_BAD_STRUCTURALLY_NEEDED},
            "enum/no-allow-alias",
        )
        bad_enums = {f.params["name"] for f in report.findings}
        assert bad_enums == {"Status"}


# ---------------------------------------------------------------------------
# enum/first-value-zero
# ---------------------------------------------------------------------------


_FIRST_VALUE_ZERO_GOOD_PROTO3 = """
syntax = "proto3";
package good;

enum Status {
  STATUS_UNSPECIFIED = 0;
  STATUS_ACTIVE = 1;
}
"""

# Proto2 grammar permits non-zero first value; buf BASIC's
# ENUM_FIRST_VALUE_ZERO still flags it, and protokit mirrors.
_FIRST_VALUE_ZERO_BAD_PROTO2 = """
syntax = "proto2";
package bad;

enum Status {
  STATUS_ACTIVE = 1;
  STATUS_INACTIVE = 2;
}
"""

# Proto2 happy path: first value IS zero. Sanity-check that the rule
# doesn't fire just because the file is proto2.
_FIRST_VALUE_ZERO_GOOD_PROTO2 = """
syntax = "proto2";
package good2;

enum Status {
  STATUS_UNSPECIFIED = 0;
  STATUS_ACTIVE = 1;
}
"""


class TestFirstValueZero:
    """``enum/first-value-zero`` fires when the first enum value's number != 0."""

    def test_happy_path_proto3_first_zero_clean(self, tmp_path: Path) -> None:
        report = _run_single(
            tmp_path,
            {"good.proto": _FIRST_VALUE_ZERO_GOOD_PROTO3},
            "enum/first-value-zero",
        )
        assert report.findings == ()

    def test_happy_path_proto2_first_zero_clean(self, tmp_path: Path) -> None:
        report = _run_single(
            tmp_path,
            {"good2.proto": _FIRST_VALUE_ZERO_GOOD_PROTO2},
            "enum/first-value-zero",
        )
        assert report.findings == ()

    def test_sad_path_proto2_first_nonzero_fires(
        self, tmp_path: Path,
    ) -> None:
        """Proto2 enum with non-zero first value fires.

        Proto3 grammar enforces zero as the first value at compile
        time, so a sad-path test under proto3 would fail to compile
        rather than reach the rule. Proto2 permits arbitrary first
        values; buf BASIC flags those cases regardless.
        """
        report = _run_single(
            tmp_path,
            {"bad.proto": _FIRST_VALUE_ZERO_BAD_PROTO2},
            "enum/first-value-zero",
        )
        # One finding on Status; params carry the offending value name
        # + its number so downstream consumers can render or aggregate.
        assert len(report.findings) == 1
        f = report.findings[0]
        assert f.params == {
            "name": "Status",
            "first_value": "STATUS_ACTIVE",
            "first_number": 1,
        }


# ---------------------------------------------------------------------------
# Profile membership — derived from RULES so future additions auto-update
# ---------------------------------------------------------------------------


_ALL_ENUM_RULE_IDS = frozenset(
    fn._lint_spec.rule_id  # type: ignore[attr-defined]
    for fn in RULES
)


class TestEnumProfileMembership:
    """``LintProfile.from_pack`` returns the expected rule_id sets.

    Per R3, ``default`` is structurally equivalent to ``recommended``
    in D6a — both contain the full enum-pack rule set. ``essentials``
    contains no enum rules (enum semantics live in recommended+).
    """

    def test_from_pack_recommended_contains_both_enum_rules(self) -> None:
        profile = LintProfile.from_pack(enum_pack, "recommended")
        assert profile.name == "recommended"
        assert profile.rule_ids == _ALL_ENUM_RULE_IDS

    def test_from_pack_default_contains_both_enum_rules(self) -> None:
        profile = LintProfile.from_pack(enum_pack, "default")
        assert profile.name == "default"
        assert profile.rule_ids == _ALL_ENUM_RULE_IDS

    def test_from_pack_essentials_contains_no_enum_rules(self) -> None:
        profile = LintProfile.from_pack(enum_pack, "essentials")
        assert profile.rule_ids == frozenset()

    def test_from_pack_unknown_profile_returns_empty(self) -> None:
        profile = LintProfile.from_pack(enum_pack, "nonexistent")
        assert profile.rule_ids == frozenset()


# ---------------------------------------------------------------------------
# Integration — both rules fire on a deliberately-bad fixture
# ---------------------------------------------------------------------------


# A proto2 enum that both sets allow_alias AND has a non-zero first
# value. Both rules should fire on the single Status descriptor.
_BOTH_BAD_FIXTURE = """
syntax = "proto2";
package badboth;

enum Status {
  option allow_alias = true;
  STATUS_ACTIVE = 1;
  STATUS_DISABLED = 1;
}
"""


class TestEnumPackIntegration:
    """Both enum rules fire on a fixture violating both."""

    def test_recommended_profile_fires_both_enum_rules(
        self, tmp_path: Path,
    ) -> None:
        result = _compile(
            tmp_path,
            {"badboth.proto": _BOTH_BAD_FIXTURE},
        )
        engine = LintEngine()
        engine.load_rule_pack(enum_pack)
        profile = LintProfile.from_pack(enum_pack, "recommended")
        report = engine.run(result, profile=profile)
        fired_rule_ids = {f.rule_id for f in report.findings}
        assert fired_rule_ids == _ALL_ENUM_RULE_IDS
