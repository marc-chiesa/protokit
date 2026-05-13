"""Parity tests for the ``naming`` rule pack — 9 rules.

Eight rules carry ``source_spec="buf:<RULE_ID>"`` and map directly
to a buf rule. The ninth — the D2 canary ``naming/snake-case-fields``
— maps via ``_CANARY_PARITY_OVERRIDE`` to buf's
``FIELD_LOWER_SNAKE_CASE`` (functional, not nominal, parity per
KTD-3 of the U8 plan).
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

#: One entry per fixture: (rule_id, fixture_subdir, proto_relpath, expected_fires).
#: Each rule has one happy-path (expected_fires=False) and one
#: sad-path (expected_fires=True) row. fixture_subdir is relative
#: to ``tests/parity/fixtures/``.
_CASES: tuple[tuple[str, str, str, bool], ...] = (
    # naming/snake-case-fields (canary; FIELD_LOWER_SNAKE_CASE via override).
    ("naming/snake-case-fields", "naming/snake-case-fields", "good.proto", False),
    ("naming/snake-case-fields", "naming/snake-case-fields", "bad.proto", True),
    # naming/pascal-case-messages → buf:MESSAGE_PASCAL_CASE.
    ("naming/pascal-case-messages", "naming/pascal-case-messages", "good.proto", False),
    ("naming/pascal-case-messages", "naming/pascal-case-messages", "bad.proto", True),
    # naming/pascal-case-enums → buf:ENUM_PASCAL_CASE.
    ("naming/pascal-case-enums", "naming/pascal-case-enums", "good.proto", False),
    ("naming/pascal-case-enums", "naming/pascal-case-enums", "bad.proto", True),
    # naming/upper-snake-case-enum-values → buf:ENUM_VALUE_UPPER_SNAKE_CASE.
    (
        "naming/upper-snake-case-enum-values",
        "naming/upper-snake-case-enum-values",
        "good.proto",
        False,
    ),
    (
        "naming/upper-snake-case-enum-values",
        "naming/upper-snake-case-enum-values",
        "bad.proto",
        True,
    ),
    # naming/snake-case-oneofs → buf:ONEOF_LOWER_SNAKE_CASE.
    ("naming/snake-case-oneofs", "naming/snake-case-oneofs", "good.proto", False),
    ("naming/snake-case-oneofs", "naming/snake-case-oneofs", "bad.proto", True),
    # naming/pascal-case-services → buf:SERVICE_PASCAL_CASE.
    ("naming/pascal-case-services", "naming/pascal-case-services", "good.proto", False),
    ("naming/pascal-case-services", "naming/pascal-case-services", "bad.proto", True),
    # naming/pascal-case-rpcs → buf:RPC_PASCAL_CASE.
    ("naming/pascal-case-rpcs", "naming/pascal-case-rpcs", "good.proto", False),
    ("naming/pascal-case-rpcs", "naming/pascal-case-rpcs", "bad.proto", True),
    # naming/snake-case-files → buf:FILE_LOWER_SNAKE_CASE.
    # Fires on filename itself, so fixture files use distinct names.
    ("naming/snake-case-files", "naming/snake-case-files", "good_file.proto", False),
    ("naming/snake-case-files", "naming/snake-case-files", "BadFile.proto", True),
    # naming/snake-case-packages → buf:PACKAGE_LOWER_SNAKE_CASE.
    ("naming/snake-case-packages", "naming/snake-case-packages", "good.proto", False),
    ("naming/snake-case-packages", "naming/snake-case-packages", "bad.proto", True),
)


class TestParityNaming:
    """One parametrized test per (rule, fixture) pair."""

    def test_every_naming_rule_has_a_parity_map_entry(self) -> None:
        """Drift guard: every parity-eligible naming rule is exercised here.

        Iterates the cases above, collects unique rule_ids, and
        asserts each is present in the conftest-derived map. If a
        future delivery adds a naming rule with ``buf:`` source_spec
        but no fixture here, this test fails and points the author
        at the gap.
        """
        case_rule_ids = {rule_id for rule_id, _, _, _ in _CASES}
        naming_parity_rules = {
            rule_id for rule_id in RULE_ID_MAP if rule_id.startswith("naming/")
        }
        missing_in_cases = naming_parity_rules - case_rule_ids
        assert not missing_in_cases, (
            f"naming family parity rules without fixtures: "
            f"{sorted(missing_in_cases)!r}. Add cases to _CASES in "
            f"tests/parity/test_parity_naming.py."
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
