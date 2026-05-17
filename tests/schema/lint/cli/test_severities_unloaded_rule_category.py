"""D6b U5 — source-discrimination contract for the two ``*_unloaded_rule`` categories.

D6b U5 split the original D6a U9 ``unloaded_rule`` category into two
distinct values so programmatic consumers can switch on ``category``
instead of matching the
``"[tool.protokit.lint.severities]"`` message substring:

- **Engine-emitted** ``unloaded_rule`` (unchanged from D6a): the
  active profile's ``rule_ids`` referenced a rule not loaded into
  the engine. Computed once at the start of ``LintEngine.run``.
- **CLI-synthesized** ``severities_unloaded_rule`` (new in D6b U5):
  a key in ``[tool.protokit.lint.severities]`` is not in the
  composed profile's ``rule_ids`` so the severity override has no
  effect. Emitted after ``LintEngine.run`` returns.

This module pins the source-discrimination contract via paired
positive + negative assertions per ce:review ADV-6 from the U5
brainstorm pass: each test asserts BOTH that the expected category
appears for its emit-site's rule_id AND that the OTHER category
does NOT carry the same rule_id. The negative assertions catch the
silent-test-confidence failure mode where a test passes for the
wrong reason because both emit paths fire for the same rule_id.

The CLI emit path is exercised end-to-end via
``[tool.protokit.lint.severities]`` (matches the natural user flow).
The engine emit path is exercised at the engine API layer (the CLI
cannot naturally produce profile.rule_ids exceeding loaded specs
because ``LintProfile.from_pack`` only adds rule_ids it just
registered — see the discussion at
``tests/schema/lint/cli/test_human_stderr_render.py:493`` for the
same constraint). Both paths flow through the same
``LintReport.runtime_warnings`` tuple and the same wire-format
emission, so testing them separately still pins the contract.
"""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from protokit.schema.lint.cli import main as lint_main
from protokit.schema.lint.engine import LintEngine
from protokit.schema.lint.model import (
    LintProfile,
    LintRuntimeWarning,
    LintSeverity,
)


def _write_pyproject_severities(
    tmp_path: Path, severities_toml: str,
) -> Path:
    """Write a minimal pyproject.toml with a [tool.protokit.lint.severities]
    table populated from the caller-supplied TOML snippet.

    Mirrors the ``_write_pyproject_severities`` helper at
    ``tests/schema/lint/cli/test_r9a_severities_overlay.py:31`` —
    duplicated rather than imported to keep this module's fixture
    surface self-contained (private test-internal helpers don't
    have a stable import contract).
    """
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        "[tool.protokit.lint]\n"
        "profile = \"default\"\n"
        f"\n[tool.protokit.lint.severities]\n{severities_toml}\n",
        encoding="utf-8",
    )
    return pyproject


class TestCliEmitSiteSourceDiscrimination:
    """The CLI-synthesized severities-overlay emit site uses the new
    ``severities_unloaded_rule`` category — NOT the engine-side
    ``unloaded_rule`` category — for the same rule_id."""

    def test_unknown_severities_key_emits_severities_unloaded_rule(
        self, tmp_path: Path, clean_descriptor_set: Path,
    ) -> None:
        """Positive assertion: a key in [tool.protokit.lint.severities]
        not in the composed profile emits a runtime warning with
        ``category="severities_unloaded_rule"`` carrying the bad key
        as ``rule_id``."""
        pyproject = _write_pyproject_severities(
            tmp_path, '"naming/does-not-exist" = "warning"',
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

        matching = [
            w for w in payload["runtime_warnings"]
            if w["category"] == "severities_unloaded_rule"
            and w["rule_id"] == "naming/does-not-exist"
        ]
        assert matching, (
            f"expected severities_unloaded_rule warning for the "
            f"unknown severities key; got "
            f"runtime_warnings={payload['runtime_warnings']!r}"
        )

    def test_unknown_severities_key_does_not_emit_unloaded_rule(
        self, tmp_path: Path, clean_descriptor_set: Path,
    ) -> None:
        """Negative assertion (source-discrimination contract): the
        SAME rule_id MUST NOT appear under the engine-side
        ``unloaded_rule`` category. If both categories fired for the
        same id, consumers switching on ``category`` would
        double-count the warning and the split would be meaningless.

        This guards against the silent-test-confidence failure mode
        per ce:review ADV-6 from the U5 brainstorm pass.
        """
        pyproject = _write_pyproject_severities(
            tmp_path, '"naming/does-not-exist" = "warning"',
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

        leaked = [
            w for w in payload["runtime_warnings"]
            if w["category"] == "unloaded_rule"
            and w["rule_id"] == "naming/does-not-exist"
        ]
        assert not leaked, (
            f"severities-overlay key MUST NOT surface under the "
            f"engine-side 'unloaded_rule' category; the source-"
            f"discrimination contract is broken. Leaked warnings: "
            f"{leaked!r}"
        )


class TestEngineEmitSiteSourceDiscrimination:
    """The engine-side ``profile.rule_ids`` ∖ loaded-rule-ids diff
    uses the original ``unloaded_rule`` category — NOT the new
    ``severities_unloaded_rule`` category — for the same rule_id.

    Exercised at the engine API layer rather than the CLI because the
    CLI's natural composition pass (``LintProfile.from_pack``) only
    adds rule_ids it just registered, so a CLI-driven engine emit
    requires the same monkeypatching workaround documented at
    ``tests/schema/lint/cli/test_human_stderr_render.py:493``. The
    direct engine call mirrors the pattern at
    ``tests/schema/lint/test_engine.py:282``
    (``test_unloaded_rule_warns_once_before_walk``).
    """

    def test_unloaded_profile_rule_emits_unloaded_rule(self) -> None:
        """Positive assertion: a ``profile.rule_ids`` entry not in the
        engine's loaded specs emits a runtime warning with
        ``category="unloaded_rule"`` carrying the missing id as
        ``rule_id``. No rule packs are loaded into the engine, so any
        named rule_id qualifies as unloaded.
        """
        from google.protobuf import descriptor_pool

        from protokit.schema.compile import CompileResult

        engine = LintEngine()
        # No load_rule_pack call — engine has zero loaded specs, so
        # every named rule_id falls into the unloaded set.
        empty = CompileResult(
            pool=descriptor_pool.DescriptorPool(),
            root_files=(),
            diagnostics=(),
        )
        report = engine.run(
            empty,
            profile=LintProfile(
                name="x",
                rule_ids=frozenset({"missing/engine-rule"}),
                min_severity=LintSeverity.INFO,
            ),
        )

        matching = [
            w for w in report.runtime_warnings
            if w.category == "unloaded_rule"
            and w.rule_id == "missing/engine-rule"
        ]
        assert matching, (
            f"expected unloaded_rule warning for the missing "
            f"profile rule_id; got runtime_warnings="
            f"{report.runtime_warnings!r}"
        )

    def test_unloaded_profile_rule_does_not_emit_severities_unloaded_rule(
        self,
    ) -> None:
        """Negative assertion (source-discrimination contract): the
        SAME rule_id MUST NOT appear under the CLI-side
        ``severities_unloaded_rule`` category. If both categories
        fired for the engine-side missing-rule case, the split would
        leak the CLI emit semantic into engine output and consumers
        would see phantom CLI warnings.

        This guards against the silent-test-confidence failure mode
        per ce:review ADV-6 from the U5 brainstorm pass.
        """
        from google.protobuf import descriptor_pool

        from protokit.schema.compile import CompileResult

        engine = LintEngine()
        empty = CompileResult(
            pool=descriptor_pool.DescriptorPool(),
            root_files=(),
            diagnostics=(),
        )
        report = engine.run(
            empty,
            profile=LintProfile(
                name="x",
                rule_ids=frozenset({"missing/engine-rule"}),
                min_severity=LintSeverity.INFO,
            ),
        )

        leaked = [
            w for w in report.runtime_warnings
            if w.category == "severities_unloaded_rule"
        ]
        assert not leaked, (
            f"engine-emit path MUST NOT surface "
            f"'severities_unloaded_rule' warnings; the source-"
            f"discrimination contract is broken. Leaked warnings: "
            f"{leaked!r}"
        )


class TestDirectConstructionSourceDiscrimination:
    """Structural assertion at the dataclass-construction layer:
    the two categories are distinct Literal values that cannot
    accidentally compare equal across emit-site shapes.

    This complements the integration tests above by pinning the
    contract at the type-system level — if a future refactor
    accidentally aliased the two values, this test fails at test
    execution time independently of the integration-layer tests
    above (the count-pin at
    ``tests/schema/lint/test_model_dataclass_changes.py:54`` is the
    sibling import-time guard against Literal-set drift).
    """

    def test_engine_emit_shape_is_distinct_from_cli_emit_shape(self) -> None:
        """Two ``LintRuntimeWarning`` instances with the SAME rule_id
        but the two different ``*unloaded_rule`` categories MUST NOT
        compare equal — even though their other fields match.
        """
        engine_emit = LintRuntimeWarning(
            category="unloaded_rule",
            rule_id="rule/same-id",
            message="rule is named in profile X but not loaded",
        )
        cli_emit = LintRuntimeWarning(
            category="severities_unloaded_rule",
            rule_id="rule/same-id",
            message=(
                "rule 'rule/same-id' is named in "
                "[tool.protokit.lint.severities] but is not in the "
                "composed profile — the severity override has no effect"
            ),
        )

        assert engine_emit != cli_emit, (
            f"the two *unloaded_rule categories must produce distinct "
            f"dataclass instances even for the same rule_id; got "
            f"engine_emit={engine_emit!r}, cli_emit={cli_emit!r}"
        )
        assert engine_emit.category != cli_emit.category
        assert engine_emit.rule_id == cli_emit.rule_id  # sanity: same id
