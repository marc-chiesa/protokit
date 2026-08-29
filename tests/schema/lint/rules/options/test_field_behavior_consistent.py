"""Tests for the D6d U2 ``options/field-behavior-consistent`` rule.

The rule validates well-formedness of declared ``(google.api.field_behavior)``
annotation lists on proto fields. Three violation arms (dict-shaped
``message_template`` per
:doc:`docs/solutions/best-practices/dict-shaped-message-template-multi-arm-rule-violation-kind-2026-05-19`):

- ``options/field-behavior-consistent/duplicate-value`` — same enum
  value appears 2+ times in the repeated annotation list.
- ``options/field-behavior-consistent/unspecified-value`` — the
  ``FIELD_BEHAVIOR_UNSPECIFIED`` zero value appears (AIP-203:
  "FIELD_BEHAVIOR_UNSPECIFIED must not be used").
- ``options/field-behavior-consistent/contradictory-pair`` — two
  semantically contradictory values both appear. Curated set:
  (OPTIONAL, REQUIRED), (REQUIRED, OUTPUT_ONLY), (INPUT_ONLY,
  OUTPUT_ONLY), (IMMUTABLE, OUTPUT_ONLY), (IMMUTABLE, INPUT_ONLY).

**Phase 0a (D6d U2) finding:** protoxy compile-FAILS on enum
identifier typos (e.g., ``= REQURIED``) and on numeric out-of-enum
literals (e.g., ``= 999``). The "INVALID identifier" and "numeric
out-of-enum" violation classes are therefore unreachable at the lint
stage — the file simply isn't in the pool. The only reachable
"invalid"-like case is the explicit ``FIELD_BEHAVIOR_UNSPECIFIED``
identifier, which surfaces normally because it's a valid enum value.
The rule's third arm is named ``unspecified-value`` rather than
``invalid-value`` to reflect this empirically-narrowed scope.

**Extension-access path:** the rule reuses U1's dynamic-pool
re-parse helpers from
:mod:`protokit.schema.lint._extension_access` so the
``(google.api.field_behavior)`` extension resolves on a protoxy-
built ``DescriptorPool`` (where the bootstrap-pool ``Extensions[]``
accessor raises ``KeyError``).

**Registration (D6d U5 delivery boundary, 0.5.0):** the rule pack
is registered in ``BUILTIN_PACKS``. These tests load the pack
explicitly via ``engine.load_rule_pack(field_behavior)`` to keep
each test scoped to the rule under examination (independent of the
BUILTIN_PACKS-curated auto-load surface). Module-import dormancy
through U2-U4 followed the
[[dormant-code-changelog-draft-staging-delivery-boundary-2026-05-17]]
discipline.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from protokit.schema.compile import compile_protos_to_result
from protokit.schema.lint._engine_run_state import engine_for_ctx
from protokit.schema.lint.engine import LintEngine
from protokit.schema.lint.model import (
    ElementKind,
    LintProfile,
    LintReport,
    LintRuleError,
    LintSeverity,
)
from protokit.schema.lint.rules.options import field_behavior
from protokit.schema.lint.rules.options.field_behavior import (
    _CONTRADICTORY_PAIRS,
    RULE_ID,
    RULES,
    check_field_behavior_consistent,
)

# ---------------------------------------------------------------------------
# Fixture proto declaring (google.api.field_behavior) extension + FieldBehavior
# enum. Self-contained mirror of google/api/field_behavior.proto (field number
# 1052 matches the real proto so a future move to vendored googleapis is
# byte-compatible). Pin protokit's dependency surface against the real proto
# by mirroring its enum values exactly (verified 2026-05-19 against
# googleapis/master).
# ---------------------------------------------------------------------------

_FIELD_BEHAVIOR_PROTO = """\
syntax = "proto3";

package google.api;

import "google/protobuf/descriptor.proto";

extend google.protobuf.FieldOptions {
    repeated google.api.FieldBehavior field_behavior = 1052;
}

enum FieldBehavior {
    FIELD_BEHAVIOR_UNSPECIFIED = 0;
    OPTIONAL = 1;
    REQUIRED = 2;
    OUTPUT_ONLY = 3;
    INPUT_ONLY = 4;
    IMMUTABLE = 5;
    UNORDERED_LIST = 6;
    NON_EMPTY_DEFAULT = 7;
    IDENTIFIER = 8;
}
"""


# ---------------------------------------------------------------------------
# Helpers — local; tests need the field_behavior pack + the field_behavior
# extension proto must be in the compile set every time. We don't use the
# shared rules/conftest helpers because they don't thread the field_behavior
# extension fixture in.
# ---------------------------------------------------------------------------


def _compile(
    tmp_path: Path,
    user_protos: dict[str, str],
    *,
    include_field_behavior: bool = True,
) -> Any:
    """Compile ``user_protos`` plus the field_behavior extension fixture.

    Args:
        tmp_path: pytest tmp_path.
        user_protos: filename → proto source. Each filename is created
            under ``tmp_path``; parent directories are created as needed.
        include_field_behavior: When True (default), prepends the
            ``google/api/field_behavior.proto`` extension fixture so
            ``(google.api.field_behavior)`` resolves in the pool. Set
            False to exercise the ``extension_unresolved`` warning path.

    Returns:
        The ``CompileResult`` from
        :func:`protokit.schema.compile.compile_protos_to_result`.
    """
    paths: list[Path] = []
    if include_field_behavior:
        fb_path = tmp_path / "google" / "api" / "field_behavior.proto"
        fb_path.parent.mkdir(parents=True, exist_ok=True)
        fb_path.write_text(_FIELD_BEHAVIOR_PROTO)
        paths.append(fb_path)
    for fname, text in user_protos.items():
        p = tmp_path / fname
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        paths.append(p)
    return compile_protos_to_result(
        paths=paths,
        proto_paths=[str(tmp_path)],
    )


def _run(
    tmp_path: Path,
    user_protos: dict[str, str],
    *,
    profile_name: str = "_test_isolation",
    rule_ids: frozenset[str] | None = None,
    include_field_behavior: bool = True,
) -> LintReport:
    """Run the engine against ``user_protos`` with the field_behavior pack."""
    result = _compile(
        tmp_path, user_protos,
        include_field_behavior=include_field_behavior,
    )
    engine = LintEngine()
    engine.load_rule_pack(field_behavior)
    profile = LintProfile(
        name=profile_name,
        rule_ids=rule_ids or frozenset({RULE_ID}),
        min_severity=LintSeverity.INFO,
    )
    return engine.run(result, profile=profile)


# Proto-source templates --------------------------------------------------

def _user_proto(field_decls: str, *, package: str = "user") -> str:
    """Build a one-message user proto importing the field_behavior extension."""
    return (
        'syntax = "proto3";\n\n'
        f"package {package};\n\n"
        'import "google/api/field_behavior.proto";\n\n'
        "message M {\n"
        f"{field_decls}\n"
        "}\n"
    )


# ---------------------------------------------------------------------------
# Module shape — RULES tuple + rule_id constant
# ---------------------------------------------------------------------------


class TestPackShape:
    """The pack exposes RULES with the single field-behavior rule."""

    def test_rules_tuple_contains_one_callable(self) -> None:
        assert isinstance(RULES, tuple)
        assert len(RULES) == 1
        assert RULES[0] is check_field_behavior_consistent
        assert hasattr(check_field_behavior_consistent, "_lint_spec")

    def test_rule_id_constant_matches_spec(self) -> None:
        spec = check_field_behavior_consistent._lint_spec  # type: ignore[attr-defined]
        assert RULE_ID == "options/field-behavior-consistent"
        assert spec.rule_id == RULE_ID


class TestRuleSpec:
    """The rule carries the expected D6d U2 spec metadata."""

    def test_spec_metadata(self) -> None:
        spec = check_field_behavior_consistent._lint_spec  # type: ignore[attr-defined]
        # Dict-shaped severity (matches dict-shaped message_template
        # per LintRuleSpec.__post_init__'s shape-pairing invariant);
        # all three arms ship at WARNING for the conservative-launch
        # posture.
        assert isinstance(spec.severity, dict)
        assert set(spec.severity.values()) == {LintSeverity.WARNING}
        assert spec.profiles == ("default",)
        assert spec.element is ElementKind.FIELD
        assert spec.source_spec == "https://google.aip.dev/203"

    def test_severity_keys_match_message_template_keys(self) -> None:
        """Dict-shaped severity + message_template MUST agree on the
        violation_kind keyset — the engine's emit-side severity
        resolution looks up per-arm severity from this same dict.
        """
        spec = check_field_behavior_consistent._lint_spec  # type: ignore[attr-defined]
        assert isinstance(spec.severity, dict)
        assert isinstance(spec.message_template, dict)
        assert set(spec.severity.keys()) == set(spec.message_template.keys())

    def test_message_template_is_dict_keyed_by_three_arms(self) -> None:
        """The dict-shaped ``message_template`` enumerates exactly the
        three violation kinds. SARIF agent-native consumers discriminate
        via ``finding.params['violation_kind']`` without parsing the
        rendered text per
        [[dict-shaped-message-template-multi-arm-rule-violation-kind-2026-05-19]].
        """
        spec = check_field_behavior_consistent._lint_spec  # type: ignore[attr-defined]
        assert isinstance(spec.message_template, dict)
        assert set(spec.message_template.keys()) == {
            "options/field-behavior-consistent/contradictory-pair",
            "options/field-behavior-consistent/duplicate-value",
            "options/field-behavior-consistent/unspecified-value",
        }
        for arm, template in spec.message_template.items():
            assert "{field_name}" in template, (
                f"arm {arm} template missing {{field_name}} placeholder"
            )


# ---------------------------------------------------------------------------
# Happy paths — well-formed annotations and no annotation
# ---------------------------------------------------------------------------


class TestHappyPath:
    def test_no_annotation_present_passes(self, tmp_path: Path) -> None:
        report = _run(
            tmp_path,
            {"user/msg.proto": _user_proto("    string a = 1;")},
        )
        assert report.findings == ()

    def test_single_well_formed_annotation_passes(self, tmp_path: Path) -> None:
        report = _run(
            tmp_path,
            {
                "user/msg.proto": _user_proto(
                    "    string a = 1 [(google.api.field_behavior) = REQUIRED];",
                ),
            },
        )
        assert report.findings == ()

    def test_two_distinct_non_contradictory_values_pass(
        self, tmp_path: Path,
    ) -> None:
        """The AIP-203 example: REQUIRED + IMMUTABLE on a single field."""
        report = _run(
            tmp_path,
            {
                "user/msg.proto": _user_proto(
                    "    string a = 1 [\n"
                    "        (google.api.field_behavior) = REQUIRED,\n"
                    "        (google.api.field_behavior) = IMMUTABLE\n"
                    "    ];",
                ),
            },
        )
        assert report.findings == ()


# ---------------------------------------------------------------------------
# Duplicate-value arm
# ---------------------------------------------------------------------------


class TestDuplicateValue:
    def test_two_required_fires_once(self, tmp_path: Path) -> None:
        report = _run(
            tmp_path,
            {
                "user/msg.proto": _user_proto(
                    "    string a = 1 [\n"
                    "        (google.api.field_behavior) = REQUIRED,\n"
                    "        (google.api.field_behavior) = REQUIRED\n"
                    "    ];",
                ),
            },
        )
        assert len(report.findings) == 1
        f = report.findings[0]
        assert f.rule_id == RULE_ID
        assert f.violation_kind == "options/field-behavior-consistent/duplicate-value"
        assert f.severity is LintSeverity.WARNING
        assert f.params["field_name"] == "a"
        assert f.params["value"] == "REQUIRED"

    def test_three_same_value_fires_once_with_value(self, tmp_path: Path) -> None:
        report = _run(
            tmp_path,
            {
                "user/msg.proto": _user_proto(
                    "    string a = 1 [\n"
                    "        (google.api.field_behavior) = OPTIONAL,\n"
                    "        (google.api.field_behavior) = OPTIONAL,\n"
                    "        (google.api.field_behavior) = OPTIONAL\n"
                    "    ];",
                ),
            },
        )
        # One finding per duplicated value (not per duplicate occurrence).
        assert len(report.findings) == 1
        assert (
            report.findings[0].violation_kind
            == "options/field-behavior-consistent/duplicate-value"
        )
        assert report.findings[0].params["value"] == "OPTIONAL"

    def test_two_distinct_duplicated_values_fire_two_findings(
        self, tmp_path: Path,
    ) -> None:
        """REQUIRED twice + IMMUTABLE twice → 2 duplicate-value findings,
        emitted in alphabetic-by-value order (IMMUTABLE before REQUIRED).
        """
        report = _run(
            tmp_path,
            {
                "user/msg.proto": _user_proto(
                    "    string a = 1 [\n"
                    "        (google.api.field_behavior) = REQUIRED,\n"
                    "        (google.api.field_behavior) = IMMUTABLE,\n"
                    "        (google.api.field_behavior) = REQUIRED,\n"
                    "        (google.api.field_behavior) = IMMUTABLE\n"
                    "    ];",
                ),
            },
        )
        dup_findings = [
            f for f in report.findings
            if f.violation_kind
            == "options/field-behavior-consistent/duplicate-value"
        ]
        assert len(dup_findings) == 2
        # Alphabetic-by-value ordering keeps engine output deterministic.
        assert dup_findings[0].params["value"] == "IMMUTABLE"
        assert dup_findings[1].params["value"] == "REQUIRED"


# ---------------------------------------------------------------------------
# Unspecified-value arm
# ---------------------------------------------------------------------------


class TestUnspecifiedValue:
    def test_field_behavior_unspecified_fires(self, tmp_path: Path) -> None:
        report = _run(
            tmp_path,
            {
                "user/msg.proto": _user_proto(
                    "    string a = 1 [\n"
                    "        (google.api.field_behavior) = "
                    "FIELD_BEHAVIOR_UNSPECIFIED\n"
                    "    ];",
                ),
            },
        )
        assert len(report.findings) == 1
        f = report.findings[0]
        assert (
            f.violation_kind
            == "options/field-behavior-consistent/unspecified-value"
        )
        assert f.params["field_name"] == "a"
        assert f.params["value"] == "FIELD_BEHAVIOR_UNSPECIFIED"


# ---------------------------------------------------------------------------
# Contradictory-pair arm
# ---------------------------------------------------------------------------


class TestContradictoryPairs:
    @pytest.mark.parametrize(
        "value_a,value_b,expected_a,expected_b",
        [
            # AIP-203-anchored contradictory pairs (alphabetic in expected output).
            ("OPTIONAL", "REQUIRED", "OPTIONAL", "REQUIRED"),
            ("REQUIRED", "OUTPUT_ONLY", "OUTPUT_ONLY", "REQUIRED"),
            ("INPUT_ONLY", "OUTPUT_ONLY", "INPUT_ONLY", "OUTPUT_ONLY"),
            ("IMMUTABLE", "OUTPUT_ONLY", "IMMUTABLE", "OUTPUT_ONLY"),
            ("IMMUTABLE", "INPUT_ONLY", "IMMUTABLE", "INPUT_ONLY"),
        ],
    )
    def test_each_curated_pair_fires(
        self,
        tmp_path: Path,
        value_a: str, value_b: str,
        expected_a: str, expected_b: str,
    ) -> None:
        """Each AIP-203 contradictory pair fires exactly once.

        ``expected_a``/``expected_b`` are the alphabetically-sorted
        renderings of the pair — the rule emits the lexicographically
        smaller member as ``value_a`` and the larger as ``value_b`` so
        the params payload is order-invariant w.r.t. proto source order.
        """
        report = _run(
            tmp_path,
            {
                "user/msg.proto": _user_proto(
                    "    string a = 1 [\n"
                    f"        (google.api.field_behavior) = {value_a},\n"
                    f"        (google.api.field_behavior) = {value_b}\n"
                    "    ];",
                ),
            },
        )
        contra = [
            f for f in report.findings
            if f.violation_kind
            == "options/field-behavior-consistent/contradictory-pair"
        ]
        assert len(contra) == 1
        f = contra[0]
        assert f.params["field_name"] == "a"
        assert f.params["value_a"] == expected_a
        assert f.params["value_b"] == expected_b

    def test_non_contradictory_pair_does_not_fire(self, tmp_path: Path) -> None:
        """REQUIRED + IMMUTABLE is the canonical AIP-203 example pair —
        not contradictory.
        """
        report = _run(
            tmp_path,
            {
                "user/msg.proto": _user_proto(
                    "    string a = 1 [\n"
                    "        (google.api.field_behavior) = REQUIRED,\n"
                    "        (google.api.field_behavior) = IMMUTABLE\n"
                    "    ];",
                ),
            },
        )
        contra = [
            f for f in report.findings
            if f.violation_kind
            == "options/field-behavior-consistent/contradictory-pair"
        ]
        assert contra == []


# ---------------------------------------------------------------------------
# Multiple violation kinds + alphabetic emission ordering
# ---------------------------------------------------------------------------


class TestMultipleViolationsAlphabeticOrder:
    def test_duplicate_plus_contradictory_emits_both(
        self, tmp_path: Path,
    ) -> None:
        """Plan scenario (line 888-891): [REQUIRED, OPTIONAL, REQUIRED]
        fires `duplicate-value` for REQUIRED pair AND `contradictory-pair`
        for REQUIRED+OPTIONAL — two distinct findings.

        Emission order: alphabetic by violation_kind suffix.
        ``contradictory-pair`` (c) precedes ``duplicate-value`` (d).
        """
        report = _run(
            tmp_path,
            {
                "user/msg.proto": _user_proto(
                    "    string a = 1 [\n"
                    "        (google.api.field_behavior) = REQUIRED,\n"
                    "        (google.api.field_behavior) = OPTIONAL,\n"
                    "        (google.api.field_behavior) = REQUIRED\n"
                    "    ];",
                ),
            },
        )
        assert len(report.findings) == 2
        kinds = [f.violation_kind for f in report.findings]
        assert kinds == [
            "options/field-behavior-consistent/contradictory-pair",
            "options/field-behavior-consistent/duplicate-value",
        ]

    def test_all_three_kinds_alphabetic_order(self, tmp_path: Path) -> None:
        """[OUTPUT_ONLY, INPUT_ONLY (contradictory), OUTPUT_ONLY (duplicate),
        FIELD_BEHAVIOR_UNSPECIFIED] fires all three arms in alphabetic
        order: contradictory-pair, duplicate-value, unspecified-value.
        """
        report = _run(
            tmp_path,
            {
                "user/msg.proto": _user_proto(
                    "    string a = 1 [\n"
                    "        (google.api.field_behavior) = OUTPUT_ONLY,\n"
                    "        (google.api.field_behavior) = INPUT_ONLY,\n"
                    "        (google.api.field_behavior) = OUTPUT_ONLY,\n"
                    "        (google.api.field_behavior) = "
                    "FIELD_BEHAVIOR_UNSPECIFIED\n"
                    "    ];",
                ),
            },
        )
        # Three arms: contradictory (INPUT_ONLY+OUTPUT_ONLY), duplicate
        # (OUTPUT_ONLY twice), unspecified (FIELD_BEHAVIOR_UNSPECIFIED).
        # NOTE: the unspecified-value participates ALSO as a candidate
        # for contradictory pairs if any future curated pair references
        # it; today none do, so only the three arms above fire.
        kinds = [f.violation_kind for f in report.findings]
        assert kinds == [
            "options/field-behavior-consistent/contradictory-pair",
            "options/field-behavior-consistent/duplicate-value",
            "options/field-behavior-consistent/unspecified-value",
        ]


# ---------------------------------------------------------------------------
# Extension-unresolved runtime warning
# ---------------------------------------------------------------------------


class TestExtensionUnresolved:
    def test_field_behavior_proto_absent_emits_warning_and_skips(
        self, tmp_path: Path,
    ) -> None:
        """When ``google/api/field_behavior.proto`` is not in the compile
        set, the rule cannot resolve the extension. It emits a single
        ``extension_unresolved`` runtime warning (per (rule_id, file)
        dedup) and produces zero findings.

        The user proto here doesn't actually USE the extension — it
        just exists in a compile set that doesn't include the
        field_behavior proto. The rule's KeyError-on-FindExtensionByName
        path fires regardless of whether the field carries the
        annotation, so the warning surfaces on every walked file.
        """
        # User proto without the field_behavior import — compiles fine.
        user_proto = (
            'syntax = "proto3";\n\n'
            "package user;\n\n"
            "message M {\n"
            "    string a = 1;\n"
            "}\n"
        )
        report = _run(
            tmp_path,
            {"user/msg.proto": user_proto},
            include_field_behavior=False,
        )
        assert report.findings == ()
        warnings = [
            w for w in report.runtime_warnings
            if w.category == "extension_unresolved"
        ]
        assert len(warnings) == 1
        w = warnings[0]
        assert w.rule_id == RULE_ID
        assert "google.api.field_behavior" in w.message
        assert "user/msg.proto" in w.message

    def test_dedup_one_warning_per_rule_file_pair(
        self, tmp_path: Path,
    ) -> None:
        """The rule walks N fields per file; the unresolved-extension
        warning must fire AT MOST ONCE per (rule_id, file_name) pair.
        """
        user_proto = (
            'syntax = "proto3";\n\n'
            "package user;\n\n"
            "message M {\n"
            "    string a = 1;\n"
            "    string b = 2;\n"
            "    string c = 3;\n"
            "}\n"
        )
        report = _run(
            tmp_path,
            {"user/msg.proto": user_proto},
            include_field_behavior=False,
        )
        warnings = [
            w for w in report.runtime_warnings
            if w.category == "extension_unresolved"
        ]
        assert len(warnings) == 1


# ---------------------------------------------------------------------------
# Profile scope — fires on `default`, NOT on `recommended`
# ---------------------------------------------------------------------------


class TestProfileScope:
    def test_default_profile_fires(self, tmp_path: Path) -> None:
        """Run with a profile named ``default`` that includes the rule —
        warnings should fire as expected on a violating field.
        """
        report = _run(
            tmp_path,
            {
                "user/msg.proto": _user_proto(
                    "    string a = 1 [\n"
                    "        (google.api.field_behavior) = REQUIRED,\n"
                    "        (google.api.field_behavior) = OPTIONAL\n"
                    "    ];",
                ),
                # ``profile_name`` doesn't matter for emission — the
                # spec's profiles=("default",) controls the COMPOSED
                # profile membership at production runtime; the test
                # uses an isolation profile so emission proves the
                # rule fires when included.
            },
            profile_name="default",
        )
        assert any(
            f.violation_kind
            == "options/field-behavior-consistent/contradictory-pair"
            for f in report.findings
        )

    def test_spec_profiles_excludes_recommended(self) -> None:
        """The rule's spec lists profiles=("default",) only.

        This is the structural assertion that the rule will NOT be in
        the ``recommended`` profile's composed rule_ids set, so
        ``recommended``-profile users see zero new findings on D6d
        upgrade per R6 of the D6d brainstorm.

        The composed-profile behavior itself is exercised by the
        engine's profile-resolution tests, not duplicated here.
        """
        spec = check_field_behavior_consistent._lint_spec  # type: ignore[attr-defined]
        assert "recommended" not in spec.profiles
        assert spec.profiles == ("default",)


# ---------------------------------------------------------------------------
# Module-level registration: IN BUILTIN_PACKS at D6d U5 (0.5.0)
# ---------------------------------------------------------------------------


class TestBuiltinPacksRegistration:
    """``options/field-behavior-consistent`` is reachable via exactly
    one ``BUILTIN_PACKS`` module (the canonical ``field_behavior`` pack).

    Live invariant guarded:

    1. ``field_behavior in BUILTIN_PACKS`` — the canonical pack is
       a member of the auto-load tuple.
    2. The rule_id ``options/field-behavior-consistent`` is exposed
       via exactly one ``BUILTIN_PACKS`` module (no rename-bypass
       attack where a contributor creates ``field_behavior_v2`` and
       registers it alongside or instead of the canonical pack —
       per ce:review ADV-5, P3, D6d U2).

    The assertion uses the typed ``get_lint_spec`` accessor from
    ``protokit.schema.lint.decorator`` rather than reaching into
    each rule's private ``_lint_spec`` attribute — see
    ``tests/schema/lint/test_builtin_packs.py`` for the canonical
    accessor pattern.
    """

    def test_rule_id_reachable_via_field_behavior_pack_in_builtin_packs(
        self,
    ) -> None:
        from protokit.schema.lint.cli import BUILTIN_PACKS
        from protokit.schema.lint.decorator import get_lint_spec

        assert field_behavior in BUILTIN_PACKS
        matching_packs = [
            pack for pack in BUILTIN_PACKS
            if any(
                get_lint_spec(r).rule_id == RULE_ID
                for r in pack.RULES
            )
        ]
        assert matching_packs == [field_behavior], (
            f"rule_id {RULE_ID!r} should be reachable via exactly the "
            f"``field_behavior`` pack in BUILTIN_PACKS, but matched "
            f"{[p.__name__ for p in matching_packs]!r}. If the rule "
            f"has been intentionally moved to another pack module, "
            f"update this assertion alongside the move."
        )


# ---------------------------------------------------------------------------
# ce:review follow-up regressions (D6d U2 ce:review 2026-05-20)
# ---------------------------------------------------------------------------


class TestCrossRunDedupReset:
    """ce:review COR-1 / ADV-1: cross-run dedup state must reset.

    Without the per-run reset (id(engine._runtime_warnings) tracking),
    a second engine.run() on the same engine would silently emit zero
    extension_unresolved warnings even though the unresolved-extension
    condition still holds. The CLI is not affected today (one
    engine.run() per process), but MCP/IDE long-lived runtimes that
    recycle engines across sessions would hit the leak.
    """

    def test_second_run_reemits_warning_on_same_engine(
        self, tmp_path: Path,
    ) -> None:
        """Run engine.run() twice on the same engine against the same
        proto file without field_behavior.proto. The second run must
        emit its own extension_unresolved warning (NOT silently
        suppress it due to dedup state from the first run).
        """
        # Two separate compile dirs (compile fails fixture across runs
        # if we reuse one tmp_path without rewriting).
        sub_a = tmp_path / "run_a"
        sub_b = tmp_path / "run_b"
        sub_a.mkdir()
        sub_b.mkdir()

        user_proto = (
            'syntax = "proto3";\n\n'
            "package user;\n\n"
            "message M {\n"
            "    string a = 1;\n"
            "}\n"
        )

        def _make_result(sub: Path) -> Any:
            p = sub / "user" / "msg.proto"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(user_proto)
            return compile_protos_to_result(
                paths=[p],
                proto_paths=[str(sub)],
            )

        result_a = _make_result(sub_a)
        result_b = _make_result(sub_b)

        engine = LintEngine()
        engine.load_rule_pack(field_behavior)
        profile = LintProfile(
            name="_test_isolation",
            rule_ids=frozenset({RULE_ID}),
            min_severity=LintSeverity.INFO,
        )

        r1 = engine.run(result_a, profile=profile)
        r2 = engine.run(result_b, profile=profile)

        warns_a = [
            w for w in r1.runtime_warnings
            if w.category == "extension_unresolved"
        ]
        warns_b = [
            w for w in r2.runtime_warnings
            if w.category == "extension_unresolved"
        ]
        assert len(warns_a) == 1
        assert len(warns_b) == 1, (
            "Second engine.run() emitted zero extension_unresolved "
            "warnings — the per-run dedup reset is broken. See "
            "ce:review COR-1/ADV-1."
        )


class TestCrossEngineDedupIsolation:
    """ce:review T-04: WeakKeyDictionary key isolation across engines.

    Engine A's dedup state must NOT suppress engine B's warning for
    the same (rule_id, file_name) pair. The WeakKeyDictionary keyed
    by engine instance provides this isolation structurally; this
    test pins the contract so a future refactor to module-level state
    surfaces immediately.
    """

    def test_independent_engines_each_emit_warning(
        self, tmp_path: Path,
    ) -> None:
        user_proto = (
            'syntax = "proto3";\n\n'
            "package user;\n\n"
            "message M {\n"
            "    string a = 1;\n"
            "}\n"
        )
        p = tmp_path / "user" / "msg.proto"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(user_proto)
        result = compile_protos_to_result(
            paths=[p],
            proto_paths=[str(tmp_path)],
        )
        profile = LintProfile(
            name="_test_isolation",
            rule_ids=frozenset({RULE_ID}),
            min_severity=LintSeverity.INFO,
        )

        engine_a = LintEngine()
        engine_a.load_rule_pack(field_behavior)
        engine_b = LintEngine()
        engine_b.load_rule_pack(field_behavior)

        r_a = engine_a.run(result, profile=profile)
        r_b = engine_b.run(result, profile=profile)

        assert len([
            w for w in r_a.runtime_warnings
            if w.category == "extension_unresolved"
        ]) == 1
        assert len([
            w for w in r_b.runtime_warnings
            if w.category == "extension_unresolved"
        ]) == 1


class TestLintRuleErrorRouting:
    """ce:review ADV-2 / REL-2 / T-03: structural-env failures inside
    the rule callable raise LintRuleError (not bare RuntimeError) so
    the engine routes them through _RULE_EXCEPTION_TUPLE and records
    a rule_exception warning rather than crashing engine.run().
    """

    def test_engine_for_ctx_raises_lint_rule_error_on_broken_emit_fn(
        self,
    ) -> None:
        """When ctx._emit_fn is not a bound method (e.g., a plain
        lambda from a test helper), engine_for_ctx raises
        LintRuleError — which is in the engine's catch tuple, so
        downstream walks continue.
        """
        from dataclasses import dataclass

        # Construct a minimal stub context where _emit_fn is a free
        # function (no __self__). Replicates the failure mode without
        # needing a real LintEngine.

        @dataclass(frozen=True)
        class _StubCtx:
            _emit_fn: Any
            _rule_id: str = "options/field-behavior-consistent"

        stub = _StubCtx(_emit_fn=lambda f: None)
        with pytest.raises(LintRuleError) as exc_info:
            engine_for_ctx(stub, RULE_ID)
        assert "options/field-behavior-consistent" in str(exc_info.value)


class TestContradictoryPairsAlphabeticInvariant:
    """ce:review MAINT-4 / ADV-3 / KP-4: alphabetic-storage convention
    of _CONTRADICTORY_PAIRS is enforced structurally.

    A future contributor adding ("REQUIRED", "OPTIONAL") instead of
    ("OPTIONAL", "REQUIRED") would cause value_a/value_b to flip in
    emitted params based on proto source order. The module-level
    assertion in field_behavior.py fires at import time; this test
    pins the contract via the public frozenset so the assertion's
    presence is also enforced.
    """

    def test_every_pair_is_alphabetically_sorted(self) -> None:
        for pair in _CONTRADICTORY_PAIRS:
            assert pair[0] < pair[1], (
                f"_CONTRADICTORY_PAIRS contains {pair!r} which is "
                f"NOT alphabetically sorted (a < b). Mis-ordered "
                f"pairs flip value_a/value_b in emitted params and "
                f"break the order-invariance contract."
            )


class TestExceptionTupleCoverage:
    """ce:review REL-1 / SEC-002: DecodeError from MergeFromString
    must be caught by the engine's rule-exception handler (not
    propagate uncaught and crash engine.run()).

    This is an engine-side fix (DecodeError added to
    _RULE_EXCEPTION_TUPLE in engine.py), so the regression test
    asserts the tuple's contents directly.
    """

    def test_decode_error_in_rule_exception_tuple(self) -> None:
        from google.protobuf.message import DecodeError

        from protokit.schema.lint.engine import _RULE_EXCEPTION_TUPLE

        assert DecodeError in _RULE_EXCEPTION_TUPLE, (
            "google.protobuf.message.DecodeError must be in "
            "_RULE_EXCEPTION_TUPLE so rules using the dynamic-pool "
            "re-parse pattern (MergeFromString on serialized options "
            "bytes) do not crash engine.run() on corrupted bytes. "
            "See ce:review REL-1 / SEC-002 (D6d U2)."
        )
