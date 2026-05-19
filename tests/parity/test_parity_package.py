"""Parity tests for the ``package`` rule pack — 2 rules.

Both rules carry ``source_spec="buf:<RULE_ID>"``. For
``package/directory-match`` the happy-path proto lives at a
subdirectory matching its package declaration, exercising buf's
relative-path → package-name comparison.
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
    # package/defined → buf:PACKAGE_DEFINED.
    ("package/defined", "package/defined", "good.proto", False),
    ("package/defined", "package/defined", "bad.proto", True),
    # package/directory-match → buf:PACKAGE_DIRECTORY_MATCH.
    # Happy proto is at parity/dirmatch/ to match its package
    # ``parity.dirmatch``; sad proto is at wrongdir/ with the
    # same package (mismatched). Both files live at non-root
    # depth because protokit's rule deliberately skips top-level
    # files (no directory to match against) while buf fires on
    # top-level files with non-empty packages — using nested
    # directories for both branches stays inside the parity-
    # testable region of the rule's behavior. (The root-level
    # divergence is a real protokit/buf difference, but exercising
    # it would require an _PARITY_EXCEPTIONS entry and four-site
    # documentation that doesn't exist yet; deferring to a
    # post-Phase-A follow-up.)
    (
        "package/directory-match",
        "package/directory-match",
        "parity/dirmatch/good.proto",
        False,
    ),
    (
        "package/directory-match",
        "package/directory-match",
        "wrongdir/bad.proto",
        True,
    ),
)


class TestParityPackage:
    def test_every_package_rule_has_a_parity_map_entry(self) -> None:
        case_rule_ids = {rule_id for rule_id, _, _, _ in _CASES}
        # Coverage scope: the original 2-rule `package` family
        # (`defined`, `directory-match`). The R7 PACKAGE_SAME_* family
        # (`package/same-*` rules — added to BUILTIN_PACKS in D6b U7)
        # has its own dedicated parity gate at
        # `tests/parity/test_parity_package_same.py` using a multi-file
        # harness against 21 buf v1.69.0 NDJSON snapshots. The D6c R8 +
        # R8b cross-file family (`package/same-directory` +
        # `package/directory-same-package`) gets its own multi-file
        # parity gate at `tests/parity/test_parity_package_directory.py`
        # (D6c U3); both families are excluded from this single-file
        # parity audit to avoid duplicate coverage.
        d6c_cross_file_rules = frozenset({
            "package/same-directory",
            "package/directory-same-package",
        })
        package_parity_rules = {
            rule_id
            for rule_id in RULE_ID_MAP
            if rule_id.startswith("package/")
            and not rule_id.startswith("package/same-")
            and rule_id not in d6c_cross_file_rules
        }
        missing = package_parity_rules - case_rule_ids
        assert not missing, (
            f"package family parity rules without fixtures: "
            f"{sorted(missing)!r}. Add cases to _CASES in "
            f"tests/parity/test_parity_package.py."
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
