"""End-to-end load-bearing R9b profile-augmentation test (D6f U2).

This file pins the sentinel-propagation contract for KD-1: setting
``[severities] "naming/snake-case-fields" = "off"`` (or any of the
four other R9b disable mechanisms) must produce ZERO findings on a
fixture that would otherwise fire the rule. Verifies the full
``cli.py`` chain — pyproject load → ``ResolvedLintConfig.from_dict`` →
unified ``disabled_rules`` → profile-augmentation subtraction →
engine setup → walk — actually suppresses at runtime.

Without the load-bearing ``effective_rule_ids = composed_profile.rule_ids
- resolved.disabled_rules`` step in ``cli.py``, the ``from_dict``
bookkeeping would silently no-op at runtime — this file is the
regression guard for that risk per the D6f U2 plan Risks &
Dependencies table.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from protokit.schema.lint.cli import main as lint_main


def _make_pyproject(tmp_path: Path, contents: str) -> Path:
    """Write ``contents`` to a tmp pyproject.toml and return its path."""
    path = tmp_path / "pyproject.toml"
    path.write_text(contents, encoding="utf-8")
    return path


def _run_lint_json(
    *,
    descriptor_set: Path,
    pyproject: Path | None,
    extra_args: tuple[str, ...] = (),
) -> dict[str, object]:
    """Invoke ``protokit lint --format=json`` and return the parsed payload.

    A non-zero exit code is allowed because findings → exit 1 is
    expected for the baseline case (un-suppressed rule fires). Tests
    assert on the parsed JSON payload, not the exit code, to keep
    the suppression contract orthogonal to the CI-gate ladder.
    """
    args: list[str] = ["--format", "json"]
    if pyproject is not None:
        args.extend(["--config", str(pyproject)])
    else:
        # Without --no-config the walk-up discovery may find an
        # ambient pyproject.toml; isolate every test invocation from
        # the project root by defaulting to --no-config when the
        # caller does not supply an explicit pyproject. Tests that
        # need pyproject behavior pass their own --config.
        args.append("--no-config")
    args.extend(extra_args)
    args.append(str(descriptor_set))
    result = CliRunner().invoke(lint_main, args)
    assert result.exit_code in (0, 1), (
        f"unexpected exit code {result.exit_code}; "
        f"stdout={result.stdout!r}; stderr={result.stderr!r}"
    )
    return json.loads(result.stdout)


class TestR9bProfileAugmentationEndToEnd:
    """The KD-1 sentinel propagation must reach the engine walk."""

    @pytest.fixture
    def baseline_fires_the_rule(
        self, bad_naming_descriptor_set: Path,
    ) -> dict[str, object]:
        """Sanity check: without any R9b directives the rule fires.

        Returns the baseline payload so individual suppression tests
        can compare the suppressed run against the same fixture's
        baseline ``findings_count``.
        """
        payload = _run_lint_json(
            descriptor_set=bad_naming_descriptor_set, pyproject=None,
        )
        findings = payload["findings"]
        assert isinstance(findings, list)
        baseline_count = sum(
            1
            for f in findings
            if isinstance(f, dict)
            and f.get("rule_id") == "naming/snake-case-fields"
        )
        assert baseline_count >= 1, (
            "test premise broken: the baseline run must fire at least "
            "one naming/snake-case-fields finding for the suppression "
            "comparison to be meaningful"
        )
        return payload

    def test_severity_off_sentinel_suppresses_to_zero(
        self,
        tmp_path: Path,
        bad_naming_descriptor_set: Path,
        baseline_fires_the_rule: dict[str, object],
    ) -> None:
        """``[severities] X = "off"`` produces ZERO findings of X."""
        del baseline_fires_the_rule  # only used for premise verification
        pyproject = _make_pyproject(
            tmp_path,
            """
            [tool.protokit.lint]
            profile = "default"

            [tool.protokit.lint.severities]
            "naming/snake-case-fields" = "off"
            """,
        )
        payload = _run_lint_json(
            descriptor_set=bad_naming_descriptor_set, pyproject=pyproject,
        )
        findings = payload["findings"]
        assert isinstance(findings, list)
        suppressed = [
            f
            for f in findings
            if isinstance(f, dict)
            and f.get("rule_id") == "naming/snake-case-fields"
        ]
        assert suppressed == [], (
            "[severities] = 'off' did not suppress the rule end-to-end: "
            f"{suppressed!r}. The KD-1 sentinel propagation contract is "
            f"broken — verify ``cli.py``'s "
            f"``composed_profile.rule_ids - resolved.disabled_rules`` "
            f"step still runs."
        )

    def test_disabled_rules_pyproject_list_suppresses_to_zero(
        self,
        tmp_path: Path,
        bad_naming_descriptor_set: Path,
    ) -> None:
        """``disabled_rules = ["X"]`` produces ZERO findings of X."""
        pyproject = _make_pyproject(
            tmp_path,
            """
            [tool.protokit.lint]
            profile = "default"
            disabled_rules = ["naming/snake-case-fields"]
            """,
        )
        payload = _run_lint_json(
            descriptor_set=bad_naming_descriptor_set, pyproject=pyproject,
        )
        findings = payload["findings"]
        assert isinstance(findings, list)
        suppressed = [
            f
            for f in findings
            if isinstance(f, dict)
            and f.get("rule_id") == "naming/snake-case-fields"
        ]
        assert suppressed == []

    def test_cli_disable_rule_flag_suppresses_to_zero(
        self,
        bad_naming_descriptor_set: Path,
    ) -> None:
        """``--disable-rule X`` produces ZERO findings of X."""
        payload = _run_lint_json(
            descriptor_set=bad_naming_descriptor_set,
            pyproject=None,
            extra_args=("--disable-rule", "naming/snake-case-fields"),
        )
        findings = payload["findings"]
        assert isinstance(findings, list)
        suppressed = [
            f
            for f in findings
            if isinstance(f, dict)
            and f.get("rule_id") == "naming/snake-case-fields"
        ]
        assert suppressed == []

    def test_clean_fixture_unaffected_by_disable(
        self, clean_descriptor_set: Path,
    ) -> None:
        """Disabling a rule on a clean fixture stays clean (no negative side-effects).

        Tests that profile-augmentation does not accidentally cause
        other rules to fire or remove rules they wouldn't have
        removed.
        """
        payload = _run_lint_json(
            descriptor_set=clean_descriptor_set,
            pyproject=None,
            extra_args=("--disable-rule", "naming/snake-case-fields"),
        )
        findings = payload["findings"]
        assert isinstance(findings, list)
        # A clean fixture should produce zero findings regardless of
        # whether the rule is disabled or not.
        assert findings == [], (
            f"--disable-rule unexpectedly produced findings on a clean "
            f"fixture: {findings!r}"
        )

    def test_all_files_excluded_and_r8b_contradiction_coexist(
        self,
        tmp_path: Path,
        bad_naming_descriptor_set: Path,
    ) -> None:
        """Excluding all files AND specifying contradictory R9b directives
        produces BOTH ``all_files_excluded`` AND ``contradictory_disable_config``
        warnings in the same payload.

        Pins the post-branch ordering: ``all_files_excluded`` (short-circuit
        path in cli.py) does NOT suppress the ``contradictory_disable_config``
        warnings that ``from_dict`` accumulated in ``resolved.runtime_warnings``.
        """
        pyproject = _make_pyproject(
            tmp_path,
            """
            [tool.protokit.lint]
            profile = "default"
            disabled_rules = ["naming/snake-case-fields"]
            enabled_rules = ["naming/snake-case-fields"]
            """,
        )
        payload = _run_lint_json(
            descriptor_set=bad_naming_descriptor_set,
            pyproject=pyproject,
            extra_args=("--exclude", "**/*.proto",),
        )
        categories = {
            w["category"]
            for w in payload["runtime_warnings"]
            if isinstance(w, dict)
        }
        assert "all_files_excluded" in categories, (
            "expected all_files_excluded warning when --exclude='**/*.proto' "
            f"is set; got categories: {sorted(categories)!r}"
        )
        assert "contradictory_disable_config" in categories, (
            "expected contradictory_disable_config warning when disabled_rules "
            "and enabled_rules both name the same rule; "
            f"got categories: {sorted(categories)!r}"
        )

    def test_disabled_rule_does_not_double_warn_with_severity_override(
        self,
        tmp_path: Path,
        bad_naming_descriptor_set: Path,
    ) -> None:
        """When a rule is BOTH in disabled_rules AND has a non-off severity
        override, the CLI emits ONE R8b warning (contradictory_disable_config)
        — NOT two (no spurious severities_unloaded_rule).

        The ``pre_disable_rule_ids`` snapshot in ``cli.py`` is what
        prevents the double-warn; this test pins that snapshot's
        intent.
        """
        pyproject = _make_pyproject(
            tmp_path,
            """
            [tool.protokit.lint]
            profile = "default"
            disabled_rules = ["naming/snake-case-fields"]

            [tool.protokit.lint.severities]
            "naming/snake-case-fields" = "warning"
            """,
        )
        payload = _run_lint_json(
            descriptor_set=bad_naming_descriptor_set, pyproject=pyproject,
        )
        warnings = payload["runtime_warnings"]
        assert isinstance(warnings, list)
        for_rule = [
            w
            for w in warnings
            if isinstance(w, dict)
            and w.get("rule_id") == "naming/snake-case-fields"
        ]
        categories = sorted(w["category"] for w in for_rule)
        assert "contradictory_disable_config" in categories, (
            f"expected R8b warning for the disabled+severity conflict, "
            f"got: {categories!r}"
        )
        assert "severities_unloaded_rule" not in categories, (
            f"spurious severities_unloaded_rule fired for an "
            f"intentionally-disabled rule — the pre_disable_rule_ids "
            f"snapshot in cli.py is broken: {categories!r}"
        )


class TestSeveritiesUnloadedRuleSuppressionForDisabledRules:
    """REL-4/ADV-002: a rule_id in BOTH ``disabled_rules`` AND
    ``[severities]`` with a non-off value must produce ONE R8b
    contradictory_disable_config warning and ZERO
    severities_unloaded_rule warnings for that rule_id.

    The ``pre_disable_rule_ids`` snapshot + ``resolved.disabled_rules``
    subtraction in cli.py is what suppresses the duplicate.
    """

    def test_disabled_and_severity_override_zero_severities_unloaded(
        self,
        tmp_path: Path,
        bad_naming_descriptor_set: Path,
    ) -> None:
        """pyproject ``disabled_rules ⊃ R`` + ``[severities] R = "warning"``
        → exactly 1 R8b contradictory_disable_config + 0
        severities_unloaded_rule for that rule_id."""
        pyproject = _make_pyproject(
            tmp_path,
            """
            [tool.protokit.lint]
            profile = "default"
            disabled_rules = ["naming/nonexistent-rule"]

            [tool.protokit.lint.severities]
            "naming/nonexistent-rule" = "warning"
            """,
        )
        result = CliRunner().invoke(
            lint_main,
            ["--format", "json", "--config", str(pyproject),
             str(bad_naming_descriptor_set)],
        )
        # Exit 0 or 1 is acceptable (findings from other rules may fire).
        assert result.exit_code in (0, 1), (
            f"unexpected exit {result.exit_code}; stderr={result.stderr!r}"
        )
        payload = json.loads(result.stdout)
        warnings = payload["runtime_warnings"]

        r8b_for_rule = [
            w for w in warnings
            if w["category"] == "contradictory_disable_config"
            and w.get("rule_id") == "naming/nonexistent-rule"
        ]
        severities_unloaded_for_rule = [
            w for w in warnings
            if w["category"] == "severities_unloaded_rule"
            and w.get("rule_id") == "naming/nonexistent-rule"
        ]
        assert len(r8b_for_rule) == 1, (
            f"expected exactly 1 R8b warning for 'naming/nonexistent-rule'; "
            f"got: {r8b_for_rule!r}; all_warnings: {warnings!r}"
        )
        assert len(severities_unloaded_for_rule) == 0, (
            f"expected 0 severities_unloaded_rule for 'naming/nonexistent-rule' "
            f"(R8b is the canonical attribution when rule is ALSO in disabled_rules); "
            f"got: {severities_unloaded_for_rule!r}"
        )


class TestNoRulesAfterDisableError:
    """COR-1: R9b directives that disable every rule in the profile
    must produce exit 2 with ``error[lint-no-rules-after-disable]:``
    rather than the misleading ``error[lint-unknown-profile]:``.
    """

    def test_all_default_rules_disabled_via_pyproject_exits_with_specific_code(
        self,
        tmp_path: Path,
        bad_naming_descriptor_set: Path,
    ) -> None:
        """When pyproject disabled_rules enumerates every rule in the
        default profile, exit 2 with ``no-rules-after-disable`` (not
        ``unknown-profile``)."""
        # Enumerate all 26 default profile rules.
        all_default_rules = [
            "naming/pascal-case-enums",
            "naming/pascal-case-messages",
            "naming/pascal-case-rpcs",
            "naming/pascal-case-services",
            "naming/snake-case-fields",
            "naming/snake-case-files",
            "naming/snake-case-oneofs",
            "naming/snake-case-packages",
            "naming/upper-snake-case-enum-values",
            "enum/first-value-zero",
            "enum/no-allow-alias",
            "imports/no-public",
            "imports/no-weak",
            "imports/unused",
            "package/defined",
            "package/directory-match",
            "package/directory-same-package",
            "package/no-import-cycle",
            "package/same-directory",
            "file/syntax-specified",
            "options/deprecated-enum-must-have-replacement-comment",
            "options/deprecated-enum-value-must-have-replacement-comment",
            "options/deprecated-field-must-have-replacement-comment",
            "options/deprecated-message-must-have-replacement-comment",
            "options/deprecated-method-must-have-replacement-comment",
            "options/field-behavior-consistent",
            "package/same-csharp-namespace",
            "package/same-go-package",
            "package/same-java-multiple-files",
            "package/same-java-package",
            "package/same-php-namespace",
            "package/same-ruby-package",
            "package/same-swift-prefix",
        ]
        rules_toml = "\n".join(
            f'  "{rid}",' for rid in all_default_rules
        )
        pyproject = _make_pyproject(
            tmp_path,
            f"""
            [tool.protokit.lint]
            profile = "default"
            disabled_rules = [
            {rules_toml}
            ]
            """,
        )
        result = CliRunner().invoke(
            lint_main,
            ["--format", "json", "--config", str(pyproject),
             str(bad_naming_descriptor_set)],
        )
        assert result.exit_code == 2, (
            f"expected exit 2 (no-rules-after-disable); "
            f"got {result.exit_code}; stderr={result.stderr!r}"
        )
        assert "error[lint-no-rules-after-disable]:" in result.stderr, (
            f"expected 'no-rules-after-disable' error code; "
            f"got stderr: {result.stderr!r}"
        )
        # Must NOT fire the misleading unknown-profile error
        assert "error[lint-unknown-profile]:" not in result.stderr, (
            f"unexpected 'unknown-profile' error — the profile WAS "
            f"declared but all rules were disabled; stderr: {result.stderr!r}"
        )

    def test_all_rules_disabled_via_cli_flag_exits_with_specific_code(
        self,
        bad_naming_descriptor_set: Path,
    ) -> None:
        """Disabling every default rule via --disable-rule flags also
        triggers ``no-rules-after-disable``."""
        all_default_rules = [
            "naming/pascal-case-enums",
            "naming/pascal-case-messages",
            "naming/pascal-case-rpcs",
            "naming/pascal-case-services",
            "naming/snake-case-fields",
            "naming/snake-case-files",
            "naming/snake-case-oneofs",
            "naming/snake-case-packages",
            "naming/upper-snake-case-enum-values",
            "enum/first-value-zero",
            "enum/no-allow-alias",
            "imports/no-public",
            "imports/no-weak",
            "imports/unused",
            "package/defined",
            "package/directory-match",
            "package/directory-same-package",
            "package/no-import-cycle",
            "package/same-directory",
            "file/syntax-specified",
            "options/deprecated-enum-must-have-replacement-comment",
            "options/deprecated-enum-value-must-have-replacement-comment",
            "options/deprecated-field-must-have-replacement-comment",
            "options/deprecated-message-must-have-replacement-comment",
            "options/deprecated-method-must-have-replacement-comment",
            "options/field-behavior-consistent",
            "package/same-csharp-namespace",
            "package/same-go-package",
            "package/same-java-multiple-files",
            "package/same-java-package",
            "package/same-php-namespace",
            "package/same-ruby-package",
            "package/same-swift-prefix",
        ]
        args: list[str] = ["--no-config", "--format", "json"]
        for rid in all_default_rules:
            args.extend(["--disable-rule", rid])
        args.append(str(bad_naming_descriptor_set))
        result = CliRunner().invoke(lint_main, args)
        assert result.exit_code == 2, (
            f"expected exit 2 (no-rules-after-disable); "
            f"got {result.exit_code}; stderr={result.stderr!r}"
        )
        assert "error[lint-no-rules-after-disable]:" in result.stderr, (
            f"expected 'no-rules-after-disable' error code; "
            f"got stderr: {result.stderr!r}"
        )
