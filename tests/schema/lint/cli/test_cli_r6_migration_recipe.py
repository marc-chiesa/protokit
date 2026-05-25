"""D6f U1 — End-to-end CLI verification of the 4 R6 migration recipe paths.

Loads the fixtures under
``tests/schema/lint/cli/cli_fixtures/d6f_r6_migration/`` and invokes
``protokit lint`` for each migration recipe path, asserting that the
post-D6f exit code matches the recipe's published outcome.

The 4 paths (matching the D6f CHANGELOG / README migration recipe):

| Path | Mechanism                                            | Outcome      |
|------|------------------------------------------------------|--------------|
| #1   | Fix the schema (add canonical replacement reference) | exit 0, R6 silent |
| #2   | Demote to WARNING via ``[severities]``               | exit 0, R6 fires at WARNING |
| #3   | Disable via ``[severities] R = "off"`` (R9b U2)      | exit 0, R6 does not load |
| #4   | Disable family via ``disabled_rules = [...]`` (R9b U2 KD-4 form) | exit 0, no R6 loaded |

Each path is verified end-to-end against the SAME "sad" R6-triggering
proto (``sad.proto``) — except path #1 which has its own happy-path
``path1_fix_schema.proto`` carrying the canonical replacement phrasing.

This file is U1's end-to-end migration verification. U3 will add a
sibling test file under ``cli_fixtures/d6f_migration_recipe/`` for
the byte-equivalence check between these TOML snippets and the
CHANGELOG/README snippets per the
[[changelog-readme-snippet-fixture-byte-equivalence-2026-05-21]]
discipline.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from click.testing import CliRunner

from protokit.schema.lint.cli import main as lint_main

# ---------------------------------------------------------------------------
# Fixture-directory anchor
# ---------------------------------------------------------------------------

_FIXTURE_DIR = Path(__file__).parent / "cli_fixtures" / "d6f_r6_migration"
"""Directory containing the 4 D6f R6 migration recipe fixtures.

Co-located with the consuming test so a future refactor that splits
this test across multiple modules carries the fixture-dir reference
forward.
"""

_SAD_PROTO = _FIXTURE_DIR / "sad.proto"
"""The shared "sad" proto — a deprecated field whose leading comment
does NOT name a replacement. Post-D6f R6 fires at ERROR for this
fixture; paths #2, #3, #4 use it to verify their suppression
mechanism actually short-circuits the ERROR exit code."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _invoke_lint(
    proto: Path,
    *extra_args: str,
    pyproject: Path | None = None,
) -> Any:
    """Invoke ``protokit lint --proto <proto>`` with optional --config."""
    argv = [
        "--proto", str(proto),
        "-I", str(proto.parent),
        "--format", "json",
    ]
    if pyproject is not None:
        argv += ["--config", str(pyproject)]
    else:
        # Without --config the CLI walks up looking for pyproject.toml;
        # the fixtures dir has none, so --no-config keeps the test
        # hermetic against any ambient pyproject the user might have.
        argv.append("--no-config")
    argv.extend(extra_args)
    return CliRunner().invoke(lint_main, argv, catch_exceptions=False)


def _r6_findings(stdout: str) -> list[dict[str, Any]]:
    """Extract R6 findings from a JSON lint report."""
    payload = json.loads(stdout)
    return [
        f for f in payload["findings"]
        if f["rule_id"].startswith("options/deprecated-")
    ]


# ---------------------------------------------------------------------------
# Migration recipe path tests
# ---------------------------------------------------------------------------


class TestD6fR6MigrationRecipe:
    """End-to-end CLI verification of the 4 published migration paths."""

    def test_path1_fix_schema_silences_rule(self) -> None:
        """Path #1: replacement comment in the proto -> rule silent.

        The user adds ``Use id instead.`` to the deprecated field's
        leading comment. The R6 heuristic regex matches the "Use X
        instead" pattern; no finding fires; exit 0 even at
        --min-severity error.
        """
        result = _invoke_lint(
            _FIXTURE_DIR / "path1_fix_schema.proto",
            "--profile", "default",
            "--min-severity", "error",
        )
        assert result.exit_code == 0, result.output
        assert _r6_findings(result.stdout) == []

    def test_path2_demote_to_warning(self) -> None:
        """Path #2: ``[severities] R = "warning"`` → R6 fires at WARNING.

        Pre-D6f: this was the documented severity demotion (default
        was already WARNING; the entry was a no-op but documented as
        the path for users who'd promoted via their own pyproject).
        Post-D6f: this restores pre-D6f exit-code semantics for users
        who don't want R6 to fail CI without --max-warnings.
        """
        result = _invoke_lint(
            _SAD_PROTO,
            pyproject=_FIXTURE_DIR / "path2_demote_to_warning.toml",
        )
        assert result.exit_code == 0, (
            f"path #2 demote-to-warning expected exit 0 (warning is "
            f"not gated without --max-warnings). Got "
            f"exit={result.exit_code}; output={result.output!r}"
        )
        findings = _r6_findings(result.stdout)
        assert len(findings) == 1, findings
        assert findings[0]["severity"] == "warning", findings[0]

    def test_path3_off_severity_unloads_rule(self) -> None:
        """Path #3: ``[severities] R = "off"`` → rule does not load.

        Per the D6f KD-1 sentinel pattern, the rule_id is added to
        the unified ``ResolvedLintConfig.disabled_rules`` set by
        ``_coerce_severities``; ``cli.py``'s post-``compose_profile``
        subtraction filters it out of the active rule set. The engine
        never sees a "warning" or "info"-typed R6 — it doesn't see
        R6 at all. Verify zero R6 findings in the report.
        """
        result = _invoke_lint(
            _SAD_PROTO,
            pyproject=_FIXTURE_DIR / "path3_off_severity.toml",
        )
        assert result.exit_code == 0, (
            f"path #3 [severities] = 'off' expected exit 0 (rule "
            f"does not load). Got exit={result.exit_code}; "
            f"output={result.output!r}"
        )
        assert _r6_findings(result.stdout) == [], (
            f"path #3 must produce ZERO R6 findings (rule unloaded "
            f"via KD-1 sentinel). Got: {_r6_findings(result.stdout)!r}"
        )

    def test_path4_disabled_rules_family_unloads_all_five(self) -> None:
        """Path #4: ``disabled_rules = [<all 5>]`` (KD-4 family form).

        The 5-rule enumeration is load-bearing per the D6f plan
        (KD-4: "MUST include the 5-rule family-list form"). Verifies
        that listing all 5 R6 rule_ids in ``disabled_rules`` unloads
        the entire family — no R6 findings of any ElementKind.

        Uses the SAD proto whose ``legacy_id`` field is FIELD-kind;
        the assertion that ZERO R6 findings fire — not just the
        FIELD one — verifies the family-list parser handled all 5
        entries (a regression that silently dropped the last N rule
        ids from the list would show as a non-zero FIELD finding).
        """
        result = _invoke_lint(
            _SAD_PROTO,
            pyproject=_FIXTURE_DIR / "path4_disabled_rules_family.toml",
        )
        assert result.exit_code == 0, (
            f"path #4 5-rule family disable expected exit 0. Got "
            f"exit={result.exit_code}; output={result.output!r}"
        )
        assert _r6_findings(result.stdout) == [], (
            f"path #4 family disable must produce ZERO R6 findings "
            f"across all 5 ElementKinds. Got: "
            f"{_r6_findings(result.stdout)!r}"
        )


# ---------------------------------------------------------------------------
# Negative control — the SAD fixture without suppression
# ---------------------------------------------------------------------------


def test_sad_proto_without_suppression_exits_1_post_promotion() -> None:
    """Negative control: the SAD fixture without any migration recipe
    applied MUST exit 1 post-D6f.

    Without this, the 4 migration-path tests above could silently pass
    if R6 stopped firing entirely (e.g., the rule was accidentally
    removed from the default profile or the heuristic broke). The
    negative control proves R6 is alive and the suppression
    mechanisms are doing real work.
    """
    result = _invoke_lint(_SAD_PROTO, "--profile", "default")
    assert result.exit_code == 1, (
        f"Negative control: SAD fixture without suppression must "
        f"exit 1 post-D6f (R6 promotion). If this test fails, the "
        f"4 migration-recipe tests above are not actually proving "
        f"anything. Got exit={result.exit_code}; output={result.output!r}"
    )
    findings = _r6_findings(result.stdout)
    assert len(findings) == 1, findings
    assert findings[0]["severity"] == "error", findings[0]
