"""Parity tests for the ``file`` rule pack — 1 rule with 2 sad branches.

``file/syntax-specified`` has a documented buf-parity divergence: at
the descriptor level, ``fdp.syntax == ""`` is emitted for both
"no syntax statement" AND explicit ``syntax = "proto2";`` files.
Protokit fires on both (descriptor-level rule); buf fires only on
the no-statement branch (source-level rule).

The divergence is documented at four sites (module docstring + rule
docstring + ``message_template`` + per-branch test methods in
``tests/schema/lint/rules/test_file.py``) per
``docs/solutions/best-practices/buf-parity-divergence-documentation-discipline-2026-05-13.md``;
the harness's fifth site is the ``_PARITY_EXCEPTIONS`` entry for
``("file/syntax-specified", "explicit_proto2")`` in
``tests/parity/conftest.py``.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pytest

from tests.parity.conftest import (
    RULE_ID_MAP,
    assert_parity,
    run_buf_lint,
    run_protokit_lint,
)

pytestmark = pytest.mark.parity

_CASES: tuple[tuple[str, str, str, bool], ...] = (
    # Happy path: explicit proto3 — neither tool fires.
    ("file/syntax-specified", "file/syntax-specified", "good.proto", False),
    # Sad path (parity holds): no syntax statement — BOTH tools fire.
    (
        "file/syntax-specified",
        "file/syntax-specified",
        "no_syntax.proto",
        True,
    ),
    # Sad path (documented divergence): explicit proto2 —
    # protokit fires, buf does not. ``expected_fires`` reflects
    # protokit behavior; ``_PARITY_EXCEPTIONS`` carries the
    # 'protokit_stricter' exception so the assertion accepts the
    # divergent shape.
    (
        "file/syntax-specified",
        "file/syntax-specified",
        "explicit_proto2.proto",
        True,
    ),
)


def _case_id(case: tuple[str, str, str, bool]) -> str:
    rule_id, _subdir, proto, fires = case
    rule_short = rule_id.split("/", 1)[1]
    fixture_stem = Path(proto).stem
    branch = "sad" if fires else "happy"
    return f"{rule_short}-{fixture_stem}-{branch}"


class TestParityFile:
    def test_every_file_rule_has_a_parity_map_entry(self) -> None:
        case_rule_ids = {rule_id for rule_id, _, _, _ in _CASES}
        file_parity_rules = {
            rule_id for rule_id in RULE_ID_MAP if rule_id.startswith("file/")
        }
        missing = file_parity_rules - case_rule_ids
        assert not missing, (
            f"file family parity rules without fixtures: "
            f"{sorted(missing)!r}. Add cases to _CASES in "
            f"tests/parity/test_parity_file.py."
        )

    @pytest.mark.parametrize(
        ("rule_id", "fixture_subdir", "proto_relpath", "expected_fires"),
        _CASES,
        ids=[_case_id(c) for c in _CASES],
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
        parity_exceptions: Mapping[tuple[str, str], tuple[str, str]],
    ) -> None:
        fixture_dir = fixtures_root / fixture_subdir
        buf_rule_id = rule_id_map[rule_id]
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
