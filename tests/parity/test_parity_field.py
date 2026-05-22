"""Parity tests for the ``field`` rule pack — 1 rule, clean parity.

``field/not-required`` (D6e U1+U2) detects proto2 ``required`` fields.
Buf v1.69.0 fires ``FIELD_NOT_REQUIRED`` under BASIC profile; protokit
fires under the opt-in ``proto2-strict`` profile (D6e KD-5: proto2-
specific strictness ships in opt-in profile per the inverted UX
philosophy at KD-1). The parity gate invokes protokit with
``--profile proto2-strict`` so byte-equivalence is the real assertion.

**Phase 0 EV-2 falsification (2026-05-22):** the brainstorm + plan
originally framed a "documented extend-block divergence" where buf
would fire ``FIELD_NOT_REQUIRED`` on extend-block ``required`` fields
while protokit (whose engine walker does not iterate
``extensions_by_name``) would not. Phase 0 falsified this premise:
both buf v1.69.0 AND protokit's compiler reject ``required``
extension fields at parse layer ("invalid cardinality: 2"). The
construct cannot be compiled, so no rule-level divergence exists.
``_PARITY_EXCEPTIONS`` carries NO entry for this rule. See
``src/protokit/schema/lint/rules/field.py`` module docstring + the
ce:compound learning at
``docs/solutions/best-practices/phase-0-empirical-verification-falsifies-brainstorm-assumption-2026-05-22.md``.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pytest

from tests.parity.conftest import (
    RULE_ID_MAP,
    ParityExceptionsMap,
    assert_parity,
    case_id,
    run_buf_lint,
    run_protokit_lint,
    skip_if_buf_deprecated,
)

pytestmark = pytest.mark.parity

#: Profile passed to ``protokit lint`` so the opt-in
#: ``proto2-strict`` rule actually runs. Without this, protokit's
#: default profile would emit zero ``field/not-required`` findings
#: and the parity gate would silently degrade to a profile-induced
#: divergence (which is true at the default-profile layer but not
#: a real capability divergence — protokit + proto2-strict matches
#: buf v1.69.0 BASIC exactly).
_PROTOKIT_PROFILE = "proto2-strict"

_CASES: tuple[tuple[str, str, str, bool], ...] = (
    # Happy path: empty proto3 stub — neither tool fires.
    ("field/not-required", "field/not-required", "good.proto", False),
    # Sad path (parity holds): proto2 required field — both tools fire.
    ("field/not-required", "field/not-required", "proto2_required.proto", True),
    # Happy path: proto2 optional field — neither tool fires.
    ("field/not-required", "field/not-required", "proto2_optional.proto", False),
    # Happy path: proto3 file with various fields — neither tool fires
    # (proto3 has no ``required`` label).
    ("field/not-required", "field/not-required", "proto3_field.proto", False),
)


class TestParityField:
    def test_every_field_rule_has_a_parity_map_entry(self) -> None:
        case_rule_ids = {rule_id for rule_id, _, _, _ in _CASES}
        field_parity_rules = {
            rule_id for rule_id in RULE_ID_MAP if rule_id.startswith("field/")
        }
        missing = field_parity_rules - case_rule_ids
        assert not missing, (
            f"field family parity rules without fixtures: "
            f"{sorted(missing)!r}. Add cases to _CASES in "
            f"tests/parity/test_parity_field.py."
        )

    @pytest.mark.parametrize(
        ("rule_id", "fixture_subdir", "proto_relpath", "expected_fires"),
        _CASES,
        ids=[case_id(c[0], c[2], c[3]) for c in _CASES],
    )
    def test_parity(
        self,
        rule_id: str,
        fixture_subdir: str,
        proto_relpath: str,
        expected_fires: bool,
        buf_binary: Path,
        fixtures_root: Path,
        rule_id_map: Mapping[str, str],
        parity_exceptions: ParityExceptionsMap,
    ) -> None:
        buf_rule_id = rule_id_map[rule_id]
        skip_if_buf_deprecated(buf_rule_id, rule_id)
        fixture_dir = fixtures_root / fixture_subdir
        protokit_findings = run_protokit_lint(
            fixture_dir,
            proto_relpath,
            profile=_PROTOKIT_PROFILE,
        )
        buf_findings = run_buf_lint(buf_binary, fixture_dir)
        assert_parity(
            protokit_findings=protokit_findings,
            buf_findings=buf_findings,
            protokit_rule_id=rule_id,
            buf_rule_id=buf_rule_id,
            proto_relpath=proto_relpath,
            expected_fires=expected_fires,
            parity_exceptions=parity_exceptions,
        )
