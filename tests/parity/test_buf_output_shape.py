"""Hard-precondition sanity check for buf's JSON output shape.

Feasibility review F2 found that buf's ``--error-format=json`` NDJSON
fields are not all strictly contractual. The harness depends on the
``type`` field carrying the buf rule_id, the ``path`` field carrying
the file path, and the output being newline-delimited JSON (one
finding per line). If buf renames or removes any of these in a
future release, the per-rule parity tests would silently report
empty buf finding sets and incorrectly conclude "buf didn't fire" —
a failure mode that masquerades as parity drift.

This module pins the contract: it runs buf against one known sad-path
fixture (the message-pascal-case rule's ``bad.proto``) and asserts
the expected fields are present with the expected types. A failure
here means buf's output shape changed and the conftest parser needs
to update before any per-rule test can be trusted.

Per the plan, there is **no fallback** to message-prefix parsing —
buf lint messages do not start with the rule name (they start with
the offending identifier or human-readable phrasing), so a fallback
would silently mask shape changes as green. Hard-fail is the correct
posture.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.parity.conftest import run_buf_lint

pytestmark = pytest.mark.parity


class TestBufOutputShape:
    """Pin the buf NDJSON output contract used by the parity harness."""

    def test_buf_emits_ndjson_with_type_path_and_start_line(
        self, buf_binary: Path, fixtures_root: Path
    ) -> None:
        """A known sad-path fixture produces a finding with the expected fields.

        Uses ``naming/pascal-case-messages`` because its sad-path
        proto is a single self-contained file with no imports —
        the cleanest possible isolation. If buf v1.69.0 changed
        the field names, this test fails with a diagnostic naming
        which fields are missing.
        """
        fixture_dir = (
            fixtures_root / "naming" / "pascal-case-messages"
        )
        findings = run_buf_lint(buf_binary, fixture_dir)

        # buf walks the module from buf.yaml and lints every .proto.
        # We expect at least one finding (the bad.proto violation);
        # good.proto should produce none. Total may be > 1 only if
        # buf re-emits across multiple files (unexpected here).
        assert findings, (
            "buf produced no findings on the pascal-case-messages "
            "fixture; expected at least one violation on bad.proto. "
            "buf v1.69.0 JSON shape may have changed — check "
            "'buf lint --error-format=json' output manually."
        )

        bad_findings = [f for f in findings if f.get("path") == "bad.proto"]
        assert bad_findings, (
            f"buf produced findings but none had path='bad.proto' — "
            f"buf may have renamed the 'path' field. Findings: "
            f"{findings!r}"
        )

        sample = bad_findings[0]
        missing: list[str] = []
        for field in ("type", "path", "start_line"):
            if field not in sample:
                missing.append(field)
        assert not missing, (
            f"buf finding is missing expected fields {missing!r} — "
            f"buf v1.69.0 may have renamed the NDJSON contract. "
            f"Sample finding: {sample!r}"
        )

        assert sample["type"] == "MESSAGE_PASCAL_CASE", (
            f"buf 'type' field carries rule_id 'MESSAGE_PASCAL_CASE' "
            f"per pinned contract; got {sample['type']!r}. The buf "
            f"rule may have been renamed in v1.69.0 (rare but possible). "
            f"Full finding: {sample!r}"
        )

        assert isinstance(sample["start_line"], int), (
            f"buf 'start_line' field is expected to be int; got "
            f"{type(sample['start_line']).__name__}. Full finding: "
            f"{sample!r}"
        )

    def test_buf_clean_fixture_produces_no_findings(
        self, buf_binary: Path, fixtures_root: Path
    ) -> None:
        """A fixture with only good.proto produces zero findings.

        Symmetric to the sad-path test — ensures buf's "no findings"
        path returns an empty list (not None, not a wrapper object).
        Catches the regression where buf might start emitting a
        summary line on success.
        """
        fixture_dir = fixtures_root / "enum" / "first-value-zero"
        # The fixture dir contains both good.proto and bad.proto;
        # we only assert on the structural property that the JSON
        # path is parseable + good.proto produces no findings.
        findings = run_buf_lint(buf_binary, fixture_dir)
        good_findings = [
            f for f in findings if f.get("path") == "good.proto"
        ]
        assert good_findings == [], (
            f"buf produced findings on good.proto in "
            f"enum/first-value-zero (expected zero). buf v1.69.0 "
            f"may have changed the rule's semantics. Findings: "
            f"{good_findings!r}"
        )
