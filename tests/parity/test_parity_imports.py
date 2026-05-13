"""Parity tests for the ``imports`` rule pack — 3 rules.

All three rules carry ``source_spec="buf:<RULE_ID>"``. Each fixture
ships an ``other.proto`` companion that the bad/good proto imports;
the fixture directory is the protokit ``-I`` import root.
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
    # imports/no-public → buf:IMPORT_NO_PUBLIC.
    ("imports/no-public", "imports/no-public", "good.proto", False),
    ("imports/no-public", "imports/no-public", "bad.proto", True),
    # imports/no-weak → buf:IMPORT_NO_WEAK.
    ("imports/no-weak", "imports/no-weak", "good.proto", False),
    ("imports/no-weak", "imports/no-weak", "bad.proto", True),
    # imports/unused → buf:IMPORT_USED.
    ("imports/unused", "imports/unused", "good.proto", False),
    ("imports/unused", "imports/unused", "bad.proto", True),
)


class TestParityImports:
    def test_every_imports_rule_has_a_parity_map_entry(self) -> None:
        case_rule_ids = {rule_id for rule_id, _, _, _ in _CASES}
        imports_parity_rules = {
            rule_id for rule_id in RULE_ID_MAP if rule_id.startswith("imports/")
        }
        missing = imports_parity_rules - case_rule_ids
        assert not missing, (
            f"imports family parity rules without fixtures: "
            f"{sorted(missing)!r}. Add cases to _CASES in "
            f"tests/parity/test_parity_imports.py."
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
