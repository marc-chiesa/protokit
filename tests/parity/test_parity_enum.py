"""Parity tests for the ``enum`` rule pack — 2 rules.

Both rules carry ``source_spec="buf:<RULE_ID>"`` and map directly
to buf's enum semantic rules.
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

_CASES: tuple[tuple[str, str, str, bool], ...] = (
    # enum/no-allow-alias → buf:ENUM_NO_ALLOW_ALIAS.
    ("enum/no-allow-alias", "enum/no-allow-alias", "good.proto", False),
    ("enum/no-allow-alias", "enum/no-allow-alias", "bad.proto", True),
    # enum/first-value-zero → buf:ENUM_FIRST_VALUE_ZERO.
    ("enum/first-value-zero", "enum/first-value-zero", "good.proto", False),
    ("enum/first-value-zero", "enum/first-value-zero", "bad.proto", True),
)


class TestParityEnum:
    def test_every_enum_rule_has_a_parity_map_entry(self) -> None:
        case_rule_ids = {rule_id for rule_id, _, _, _ in _CASES}
        enum_parity_rules = {
            rule_id for rule_id in RULE_ID_MAP if rule_id.startswith("enum/")
        }
        missing = enum_parity_rules - case_rule_ids
        assert not missing, (
            f"enum family parity rules without fixtures: {sorted(missing)!r}. "
            f"Add cases to _CASES in tests/parity/test_parity_enum.py."
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
        protokit_findings = run_protokit_lint(fixture_dir, proto_relpath)
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
