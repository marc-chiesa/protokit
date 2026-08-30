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

import types
from pathlib import Path
from typing import Any

import pytest

from protokit import _cli_utils
from protokit.schema.lint.engine import LintEngine
from protokit.schema.lint.model import ElementKind, LintProfile, LintSeverity
from protokit.schema.lint.rules import enum as enum_pack
from protokit.schema.lint.rules.enum import (
    RULES,
    check_first_value_zero,
    check_no_allow_alias,
)

from .conftest import _compile
from .conftest import _run_single as _run_single_with_pack


def _run_single(
    tmp_path: Path,
    sources: dict[str, str],
    rule_id: str,
) -> Any:
    """Thin wrapper that fixes the pack to ``enum`` for this file's tests."""
    return _run_single_with_pack(tmp_path, sources, rule_id, enum_pack)


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

    @pytest.mark.skipif(
        not _cli_utils._has_protoxy(),
        reason=(
            "fixture sets `option allow_alias = true` on an enum with no "
            "actual aliasing — strict protoc (3.21+) rejects this at parse "
            "time with `declares support for enum aliases but no enum values "
            "share field numbers`, so the lint rule never sees the "
            "descriptor. Protoxy's embedded protoc permits it; this test "
            "verifies the rule fires on that shape and is meaningful only on "
            "the protoxy backend"
        ),
    )
    def test_sad_path_allow_alias_without_actual_alias_fires(
        self, tmp_path: Path,
    ) -> None:
        report = _run_single(
            tmp_path,
            {"bad.proto": _NO_ALIAS_BAD_NO_ACTUAL_ALIAS},
            "enum/no-allow-alias",
        )
        # Pin count so a double-fire regression (e.g., the rule
        # firing once per enum value rather than per enum) fails the
        # assertion that a set comparison would silently collapse.
        assert len(report.findings) == 1
        f = report.findings[0]
        assert f.violation_kind == "enum/no-allow-alias"
        assert f.params == {"name": "Status"}

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
        assert len(report.findings) == 1
        f = report.findings[0]
        assert f.violation_kind == "enum/no-allow-alias"
        assert f.params == {"name": "Status"}


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
        assert f.violation_kind == "enum/first-value-zero"
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
        # Pin the count too: the fixture has exactly one enum (Status),
        # and each rule should fire exactly once on it. A set-only
        # assertion would silently accept regressions where one rule
        # fires twice and the other zero times.
        assert len(report.findings) == 2
        fired_rule_ids = {f.rule_id for f in report.findings}
        assert fired_rule_ids == _ALL_ENUM_RULE_IDS


class TestEmptyEnumGuard:
    """``check_first_value_zero`` returns on an enum with no values.

    The protobuf descriptor pool refuses to build an enum with zero values
    ("enums must contain at least one value"), so this branch is unreachable
    from any compiled fixture — which is why a mutation audit could turn the
    guard's ``return`` into an ``IndexError`` with the whole suite green. The
    rule's own docstring names the case it guards: a *synthetic* descriptor.

    So the test supplies exactly that — a stub context, the same shape the
    engine builds, standing in for a descriptor the pool would not accept. It
    pins the contract at the level the guard actually protects: the callable's,
    not the compiler's.
    """

    class _StubEnum:
        name = "Synthetic"
        values: tuple[Any, ...] = ()

    class _StubCtx:
        enum = None  # replaced per-instance

        def __init__(self) -> None:
            self.enum = TestEmptyEnumGuard._StubEnum()
            self.emitted: list[dict[str, Any]] = []

        def emit(self, **kwargs: Any) -> None:
            self.emitted.append(kwargs)

    def test_valueless_enum_returns_without_emitting(self) -> None:
        ctx = self._StubCtx()
        check_first_value_zero(ctx)  # type: ignore[arg-type]
        assert ctx.emitted == []

    def test_a_populated_enum_still_evaluates(self) -> None:
        """Guards against a fix that returns for every enum."""
        ctx = self._StubCtx()
        first = types.SimpleNamespace(number=7, name="SEVEN")
        ctx.enum.values = (first,)
        check_first_value_zero(ctx)  # type: ignore[arg-type]
        assert len(ctx.emitted) == 1
        assert ctx.emitted[0]["violation_kind"] == "enum/first-value-zero"
