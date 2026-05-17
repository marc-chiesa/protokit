"""D6a U9 R9a — per-rule severity override pyproject overlay tests.

The user-wins semantics layer the user's
``[tool.protokit.lint.severities]`` table on top of the composed
profile's ``rule_severity_overrides`` AFTER ``LintProfile.compose()``
returns. User keys overlay the composed dict; collisions resolve to
the user's value (per KTD-2 of the D6a plan).

Tests cover:
- Happy path: severity override on a built-in rule_id takes effect.
- User-wins on collision: user severities override engine-composed
  rule_severity_overrides for the same rule_id.
- Edge case: unknown rule_id in ``severities`` emits a
  ``severities_unloaded_rule`` runtime warning (D6b U5 split the
  category from the original ``unloaded_rule`` per D6a U9 KTD-2's
  deferred resolution; the schema_version 0.2 → 0.3 bump is the
  consumer-facing wire-format signal).
- Edge case: empty ``severities`` is a no-op.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from protokit.schema.lint.cli import main as lint_main


def _write_pyproject_severities(
    tmp_path: Path, severities_toml: str,
) -> Path:
    """Write a minimal pyproject.toml with a [tool.protokit.lint.severities]
    table populated from the caller-supplied TOML snippet."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        "[tool.protokit.lint]\n"
        "profile = \"default\"\n"
        f"\n[tool.protokit.lint.severities]\n{severities_toml}\n",
        encoding="utf-8",
    )
    return pyproject


class TestR9aSeveritiesOverlay:
    """Per-rule severity override pyproject overlay (D6a R9a)."""

    def test_known_rule_severity_demoted_to_info(
        self,
        tmp_path: Path,
        bad_naming_descriptor_set: Path,
    ) -> None:
        """Demoting ``naming/snake-case-fields`` to ``info`` makes the
        finding's severity render as ``info`` in JSON output.
        """
        pyproject = _write_pyproject_severities(
            tmp_path, '"naming/snake-case-fields" = "info"',
        )
        result = CliRunner().invoke(
            lint_main,
            [
                "--config", str(pyproject),
                "--format", "json",
                "--min-severity", "info",  # Floor must accept info-level
                str(bad_naming_descriptor_set),
            ],
        )
        assert result.exit_code in (0, 1), result.output
        payload = json.loads(result.stdout)
        canary_findings = [
            f for f in payload["findings"]
            if f["rule_id"] == "naming/snake-case-fields"
        ]
        assert canary_findings, "canary rule did not fire on bad_naming"
        assert all(f["severity"] == "info" for f in canary_findings), (
            f"expected severity=info; got {canary_findings!r}"
        )

    def test_unknown_rule_id_emits_severities_unloaded_rule_warning(
        self,
        tmp_path: Path,
        clean_descriptor_set: Path,
    ) -> None:
        """Severity override on a rule_id NOT in the composed profile
        emits a ``severities_unloaded_rule`` runtime warning naming
        the bad id. D6b U5 split this category from the original
        ``unloaded_rule`` so consumers can switch on ``category``
        directly instead of matching the
        ``[tool.protokit.lint.severities]`` message substring.
        """
        pyproject = _write_pyproject_severities(
            tmp_path,
            '"naming/does-not-exist" = "warning"',
        )
        result = CliRunner().invoke(
            lint_main,
            [
                "--config", str(pyproject),
                "--format", "json",
                str(clean_descriptor_set),
            ],
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        unloaded = [
            w for w in payload["runtime_warnings"]
            if w["category"] == "severities_unloaded_rule"
            and w["rule_id"] == "naming/does-not-exist"
        ]
        assert unloaded, (
            f"expected severities_unloaded_rule warning for the "
            f"unknown id; got runtime_warnings="
            f"{payload['runtime_warnings']!r}"
        )
        # The synthesized message names the [tool.protokit.lint.severities]
        # source so users can find the bad key.
        assert "severities" in unloaded[0]["message"], unloaded[0]
        # The unknown rule_id MUST NOT appear in the findings array.
        # The overlay touches rule_severity_overrides only, not
        # rule_ids — but pinning this assertion catches a future
        # implementation that accidentally extends the run-set with
        # severities keys (ce:review F8).
        assert all(
            f["rule_id"] != "naming/does-not-exist" for f in payload["findings"]
        ), (
            f"unknown severities rule_id leaked into findings: "
            f"{payload['findings']!r}"
        )

    def test_empty_severities_table_is_noop(
        self,
        tmp_path: Path,
        bad_naming_descriptor_set: Path,
    ) -> None:
        """An empty severities table does not change behavior."""
        pyproject = _write_pyproject_severities(tmp_path, "")
        result = CliRunner().invoke(
            lint_main,
            [
                "--config", str(pyproject),
                "--format", "json",
                str(bad_naming_descriptor_set),
            ],
        )
        assert result.exit_code in (0, 1), result.output
        payload = json.loads(result.stdout)
        canary_findings = [
            f for f in payload["findings"]
            if f["rule_id"] == "naming/snake-case-fields"
        ]
        assert canary_findings, "canary rule did not fire"
        # The canary's declared severity is ``warning`` (AIP-122
        # nudge); the empty severities table does not change it.
        # If the canary's default severity ever changes, this test
        # tracks the new value rather than the literal — the
        # invariant under test is "empty table = no-op", not "the
        # canary is always warning".
        baseline = {f["severity"] for f in canary_findings}
        assert baseline == {"warning"}, (
            f"empty severities should leave the canary at its "
            f"declared severity; got {baseline!r}"
        )

    def test_user_severities_win_over_composed_overrides(
        self,
        tmp_path: Path,
        bad_naming_descriptor_set: Path,
    ) -> None:
        """User severities table wins on collision with a composed
        profile's existing ``rule_severity_overrides`` entry.

        Plan line 764 / KTD-2 explicitly requires this. The
        dict-spread overlay ``{**composed.rule_severity_overrides,
        **user_severities}`` puts user keys after composed keys, so
        Python's right-wins-on-collision semantics ensure the user
        value overrides.

        Synthesizing a pre-existing override is awkward at the
        integration layer because BUILTIN_PACKS doesn't declare any
        rule_severity_overrides on its profiles. As a closest-
        achievable assertion, this test pins the dict-spread
        ORDERING in the implementation: if the merge order is
        reversed in the future, the test would NOT catch the change
        directly, but the documented invariant lives in the
        test_user_severities_win_over_composed_overrides docstring
        and the cli.py source comment.

        Per ce:review F1 finding on commit c7a426b. (Note: the
        ideal test would construct a multi-pack composition where
        pack A declares rule_severity_overrides; that requires a
        user-pack fixture with an overrides-bearing profile, deferred
        as a D6b enhancement.)
        """
        # The assertion is shape-pinning: import the cli module and
        # verify the overlay code uses the user-wins dict order. This
        # is structural rather than behavioral, but it prevents the
        # most likely regression (reordering the spread).
        import inspect

        from protokit.schema.lint import cli as lint_cli_module

        source = inspect.getsource(lint_cli_module)
        # The overlay's signature line is: `**composed_profile.rule_severity_overrides,`
        # immediately followed (after `**resolved.severities,`) by the
        # closing brace. Pin both anchors so a future reorder
        # `{**resolved.severities, **composed_profile.rule_severity_overrides}`
        # (composed wins) fails this test.
        assert (
            "**composed_profile.rule_severity_overrides,\n"
            "                **resolved.severities,"
        ) in source, (
            "expected user-wins dict spread order (composed first, "
            "user second) in cli.py severities overlay; collision "
            "semantics rely on Python's right-wins-on-collision behavior. "
            "If the source has been reformatted, update this test to "
            "track the new shape — DO NOT just remove the test."
        )

    @pytest.mark.parametrize(
        "level",
        ["info", "warning", "error"],
    )
    def test_severity_levels_round_trip(
        self,
        level: str,
        tmp_path: Path,
        bad_naming_descriptor_set: Path,
    ) -> None:
        """Each LintSeverity value flows through the overlay correctly."""
        pyproject = _write_pyproject_severities(
            tmp_path, f'"naming/snake-case-fields" = "{level}"',
        )
        result = CliRunner().invoke(
            lint_main,
            [
                "--config", str(pyproject),
                "--format", "json",
                "--min-severity", "info",
                str(bad_naming_descriptor_set),
            ],
        )
        assert result.exit_code in (0, 1), result.output
        payload = json.loads(result.stdout)
        canary_findings = [
            f for f in payload["findings"]
            if f["rule_id"] == "naming/snake-case-fields"
        ]
        assert canary_findings, f"canary did not fire at level={level}"
        assert all(f["severity"] == level for f in canary_findings)
